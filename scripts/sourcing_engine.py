"""
赣丰玻纤 · 选品评分引擎（Sourcing Scoring Engine）
====================================================

按 V5 方案里的 6 维模型：
  市场规模 25% + 增速 20% + 产线匹配 20% + 毛利率 15% + 认证/壁垒 10% + 出海易度 10%

输入：12 SKU + 免费数据源聚合结果
输出：每个 SKU 的 6 维分 + 总分 + 推荐理由 + 目标市场

实现要点：
- 完全离线可运行（demo 模式）
- 通过 data loader 加载 free_data_sources 实时数据
- 输出格式与飞书多维表格字段严格对应，方便后续接入
"""
from __future__ import annotations
import json
import os
import sys
import logging
from typing import Any

logger = logging.getLogger("sourcing")

THIS_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, THIS_DIR)
from free_data_sources import DataAggregator  # type: ignore
from llm_client import chat_completion, is_available  # type: ignore

DATA_DIR = os.path.join(THIS_DIR, "..", "data")
SKU_FILE = os.path.join(DATA_DIR, "sku.json")


# 6 维评分权重（V5 方案）
WEIGHTS = {
    "market": 0.25,
    "growth": 0.20,
    "fit": 0.20,
    "margin": 0.15,
    "barrier": 0.10,
    "sea": 0.10,
}
assert abs(sum(WEIGHTS.values()) - 1.0) < 1e-9


def _load_skus() -> list[dict[str, Any]]:
    with open(SKU_FILE, "r", encoding="utf-8") as f:
        return json.load(f)["products"]


# -----------------------------------------------------------
# 维度计算（确定性，无 LLM 依赖）
# -----------------------------------------------------------
def _calc_market(sku: dict, agg: DataAggregator) -> tuple[float, dict]:
    """市场规模（25%） - 0-10 分"""
    comtrade = agg.comtrade.fetch()["metrics"]
    # 不同场景对应的市场规模权重不同
    weight_by_scenario = {
        "外墙保温": 1.0,
        "EIFS 抹面层": 0.95,
        "防水卷材增强": 0.85,
        "石膏板接缝": 0.92,
        "海工防腐": 0.6,
        "光伏背板增强": 0.7,
        "GRC 永久性建筑": 0.7,
        "防火风管": 0.5,
    }
    scenarios = sku.get("scenarios", [])
    w = max((weight_by_scenario.get(s, 0.6) for s in scenarios), default=0.6)

    # 基准分由 Comtrade 实测的 HS7019 全球进口规模决定，而非写死
    size_b = comtrade["global_import_usd_billion"]
    if size_b >= 8:
        base_score = 8.5
    elif size_b >= 6:
        base_score = 8.0
    elif size_b >= 4:
        base_score = 7.5
    else:
        base_score = 7.0

    score = base_score * w
    top3 = comtrade.get("top_importers_2024", [])[:3]
    return min(10.0, max(1.0, score)), {
        "global_import_usd_b": size_b,
        "yoy_growth_pct": comtrade["yoy_growth_pct"],
        "data_year": agg._cached(agg.comtrade).get("data_year"),
        "data_status": agg._cached(agg.comtrade).get("status"),
        "top_importers": [f"{t['country']} ${t['import_usd_million']:.0f}M" for t in top3],
        "scenario_weight": w,
        "base_score": base_score,
    }


def _calc_growth(sku: dict, agg: DataAggregator) -> tuple[float, dict]:
    """增速（20%） - 0-10 分。

    主信号是同比增速：Google Trends 的同比只有在关键词搜索量足够大时才可信，
    否则退回 Comtrade 的真实进口额同比（见 free_data_sources.score_one_sku）。
    再叠加一个 ±0.5 分的微调，反映该品类在 Trends 里的相对需求强度——绝对
    同比不可信，但「哪个品类被搜得更多」这个相对排序是可用的。
    """
    sku_trend = agg.score_one_sku(sku)
    yoy = sku_trend["yoy_change_pct"] or 0.0
    if yoy >= 15:
        base = 9.5
    elif yoy >= 10:
        base = 8.5
    elif yoy >= 6:
        base = 7.5
    elif yoy >= 3:
        base = 6.5
    elif yoy >= 0:
        base = 5.5
    else:
        base = 4.0

    percentile = sku_trend.get("demand_percentile", 0.5)
    adjust = round((percentile - 0.5) * 1.0, 2)
    score = min(10.0, max(1.0, base + adjust))

    return score, {
        "trend_yoy_change_pct": yoy,
        "base_score": base,
        "demand_percentile": percentile,
        "demand_adjust": adjust,
        "trend_score_0_100": round(sku_trend["trend_score"] * 10, 1),
        "matched_keyword": sku_trend.get("matched_keyword"),
        "growth_basis": sku_trend.get("growth_basis"),
        "trend_confidence": sku_trend.get("trend_confidence"),
    }


def _calc_fit(sku: dict) -> tuple[float, dict]:
    """产线匹配（20%） - 是否匹配现有 145-200g 主流产线。
       现产线覆盖范围：75-280g 自粘/涂层/无碱/抗碱"""
    g = sku["gram"] if isinstance(sku["gram"], (int, float)) else 150
    if 100 <= g <= 200:
        base = 9.0
    elif 75 <= g < 100 or 200 < g <= 220:
        base = 8.0
    elif g < 75:
        base = 7.0
    elif 220 < g <= 280:
        base = 6.5
    else:
        base = 5.0
    if sku.get("sku") == "GF-OM-CUSTOM":
        base = 6.5
    return base, {"gram_g": g, "production_line_match": "core 145-200g"}


def _calc_margin(sku: dict) -> tuple[float, dict]:
    """毛利率（15%） - 用单价 / 单成本估算。
       假设行业基线 0.30 USD/sqm 毛利率约 30%, 0.40 USD/sqm 约 35%。"""
    price = sku.get("target_price_usd_per_sqm", 0.3)
    cost = sku.get("unit_cost_cny", 1.0) / 7.2  # CNY → USD 粗略
    if cost <= 0:
        return 7.0, {"margin_assumed_pct": 30}
    gross_pct = max(0, (price - cost) / price) * 100
    score = min(10.0, max(3.0, gross_pct / 4.5))  # 30% → 6.7, 35% → 7.8
    return round(score, 1), {"margin_assumed_pct": round(gross_pct, 1)}


def _calc_barrier(sku: dict) -> tuple[float, dict]:
    """认证/壁垒（10%） - 是否有标准认证 + 技术门槛。"""
    special = ["marine", "fire", "solar", "grc"]
    name = sku["name_en"].lower()
    score = 5.5
    matched = []
    for kw in special:
        if kw in name:
            score += 1.5
            matched.append(kw)
    score = min(10.0, score)
    return score, {"special_features": matched, "factory_certs": ["ISO 9001", "CE"]}


def _calc_sea(sku: dict, agg: DataAggregator) -> tuple[float, dict]:
    """出海易度（10%） - 真实关税 + 需求动能 + 公司既有出口经验。

    三者加权：出口经验 50% / 关税友好度 30% / 建筑需求动能 20%。
    关税与动能来自 WITS 与 World Bank 实时数据。
    """
    # 公司在各市场的既有出口经验（人工维护的业务知识）
    market_experience = {
        "Saudi Arabia": 1.0, "UAE": 1.0, "Vietnam": 1.0,
        "India": 0.9, "Brazil": 0.8, "Turkey": 0.85,
        "Germany": 0.7, "France": 0.7, "USA": 0.7, "Mexico": 0.7,
    }
    exp_avg = sum(market_experience.values()) / len(market_experience)

    tariffs = agg.tariff_map()
    momentum = agg.momentum_map()

    # 关税友好度：按出口经验加权的平均关税，15% 以上视为很不友好
    weighted, wsum = 0.0, 0.0
    for country, w in market_experience.items():
        t = tariffs.get(country)
        if t is not None:
            weighted += t * w
            wsum += w
    avg_tariff = (weighted / wsum) if wsum else 8.0
    tariff_friendly = max(0.0, min(1.0, 1.0 - avg_tariff / 15.0))

    # 需求动能：取经验市场的平均动能指数（0-100 → 0-1）
    mom_vals = [momentum[c] for c in market_experience if momentum.get(c) is not None]
    mom_avg = (sum(mom_vals) / len(mom_vals) / 100.0) if mom_vals else 0.4

    composite = exp_avg * 0.5 + tariff_friendly * 0.3 + mom_avg * 0.2
    score = 4.0 + composite * 6.0
    return round(min(10.0, max(1.0, score)), 1), {
        "company_export_avg_experience_pct": round(exp_avg * 100, 0),
        "avg_mfn_tariff_pct": round(avg_tariff, 2),
        "tariff_friendly_0_1": round(tariff_friendly, 2),
        "construction_momentum_avg": round(mom_avg * 100, 1),
        "tariff_data_status": agg._cached(agg.wits).get("status"),
        "macro_data_status": agg._cached(agg.worldbank).get("status"),
    }


# -----------------------------------------------------------
# 主评分入口
# -----------------------------------------------------------
def score_one(sku: dict, agg: DataAggregator) -> dict[str, Any]:
    m, m_d = _calc_market(sku, agg)
    g, g_d = _calc_growth(sku, agg)
    f, f_d = _calc_fit(sku)
    mg, mg_d = _calc_margin(sku)
    b, b_d = _calc_barrier(sku)
    s, s_d = _calc_sea(sku, agg)

    total = (
        WEIGHTS["market"] * m
        + WEIGHTS["growth"] * g
        + WEIGHTS["fit"] * f
        + WEIGHTS["margin"] * mg
        + WEIGHTS["barrier"] * b
        + WEIGHTS["sea"] * s
    )

    return {
        "sku": sku["sku"],
        "name_zh": sku["name_zh"],
        "name_en": sku["name_en"],
        "dimensions": {
            "market": {"score": round(m, 2), "detail": m_d},
            "growth": {"score": round(g, 2), "detail": g_d},
            "fit": {"score": round(f, 2), "detail": f_d},
            "margin": {"score": round(mg, 2), "detail": mg_d},
            "barrier": {"score": round(b, 2), "detail": b_d},
            "sea": {"score": round(s, 2), "detail": s_d},
        },
        "total_score": round(total, 2),
        "tier": "T1" if total >= 8.0 else ("T2" if total >= 7.0 else ("T3" if total >= 6.0 else "T4")),
        "recommend_actions": _recommend_actions(sku, total),
    }


def _recommend_actions(sku: dict, score: float) -> list[str]:
    actions = []
    if score >= 8.5:
        actions.append("🔥 建议立即立项，作为主打 SKU 重点推广")
        actions.append("🎯 同步建立该 SKU 在 T1 市场（沙特/阿联酋/越南）的样品库")
        actions.append("📑 在阿里国际站主页置顶该 SKU 详情页")
    elif score >= 8.0:
        actions.append("✅ 建议 M+1 立项，配合 1-2 个重点市场深耕")
        actions.append("📧 主动邀请老客户试用，赠送 5 卷样品 + 运费减免")
    elif score >= 7.0:
        actions.append("🟡 列入备选 SKU，等老 SKU 巩固后再上")
        actions.append("🤝 可主动寻找 OEM 客户，按需定制")
    else:
        actions.append("🟢 暂不主动推广，仅作为询盘响应选项")
    return actions


def _generate_ai_insights(results: list[dict[str, Any]]) -> None:
    """用 DeepSeek 为 Top 5 SKU 生成 AI 推荐理由（原地修改 results）"""
    if not is_available():
        logger.info("DeepSeek not available, skipping AI insights")
        return

    top5 = results[:5]
    sku_summaries = []
    for r in top5:
        d = r["dimensions"]
        sku_summaries.append(
            f"- {r['sku']} ({r['name_en']}): 总分 {r['total_score']} (Tier {r['tier']})\n"
            f"  市场={d['market']['score']} 增速={d['growth']['score']} "
            f"匹配={d['fit']['score']} 毛利={d['margin']['score']} "
            f"壁垒={d['barrier']['score']} 出海={d['sea']['score']}"
        )
    sku_text = "\n".join(sku_summaries)

    system_prompt = f"""你是赣丰玻纤的外贸选品顾问。根据以下 5 款 SKU 的 6 维评分结果，为每款生成简短的选品建议。

评分维度：市场规模(25%) + 增速(20%) + 产线匹配(20%) + 毛利率(15%) + 认证壁垒(10%) + 出海易度(10%)

SKU 评分数据：
{sku_text}

请为每款 SKU 输出一行 JSON，格式：
{{"sku":"SKU编号","ai_reason":"一句话推荐理由（中文，30字内）","target_market":"目标市场（1-2个国家）","suggested_action":"建议动作（中文，20字内）"}}

只输出 JSON 数组，不要其他文字。"""

    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": "请生成选品建议。"},
    ]

    try:
        raw = chat_completion(messages, temperature=0.3, max_tokens=600)
        if not raw:
            logger.warning("AI insights: empty response")
            return

        # 提取 JSON（容错：去掉可能的 markdown 代码块标记）
        clean = raw.strip()
        if clean.startswith("```"):
            clean = clean.split("\n", 1)[1] if "\n" in clean else clean[3:]
        if clean.endswith("```"):
            clean = clean.rsplit("```", 1)[0]
        clean = clean.strip()

        insights = json.loads(clean)
        insight_map = {item["sku"]: item for item in insights}
        for r in results:
            if r["sku"] in insight_map:
                ins = insight_map[r["sku"]]
                r["ai_reason"] = ins.get("ai_reason", "")
                r["target_market"] = ins.get("target_market", "")
                r["suggested_action"] = ins.get("suggested_action", "")
        logger.info("AI insights generated for %d SKUs", len(insight_map))
    except Exception as e:
        logger.error("AI insights generation failed: %s", e)


def score_all() -> list[dict[str, Any]]:
    agg = DataAggregator()
    skus = _load_skus()
    results = [score_one(s, agg) for s in skus]
    results.sort(key=lambda x: x["total_score"], reverse=True)

    # 用 DeepSeek 为 Top 5 生成 AI 推荐理由
    _generate_ai_insights(results)

    return results


if __name__ == "__main__":
    res = score_all()
    print(json.dumps(res, indent=2, ensure_ascii=False, default=str))
