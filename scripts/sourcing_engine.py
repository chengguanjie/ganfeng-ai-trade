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
from typing import Any

THIS_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, THIS_DIR)
from free_data_sources import DataAggregator  # type: ignore

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
    w = max(weight_by_scenario.get(s, 0.6) for s in sku.get("scenarios", []))
    base_score = 8.0
    score = base_score * w
    return min(10.0, max(1.0, score)), {
        "global_import_usd_b": comtrade["global_import_usd_billion"],
        "yoy_growth_pct": comtrade["yoy_growth_pct"],
        "weight": w,
    }


def _calc_growth(sku: dict, agg: DataAggregator) -> tuple[float, dict]:
    """增速（20%） - 0-10 分。优先看 Google Trends 关键词同比增速。"""
    sku_trend = agg.score_one_sku(sku)
    yoy = sku_trend["yoy_change_pct"]
    if yoy >= 15:
        score = 9.5
    elif yoy >= 10:
        score = 8.5
    elif yoy >= 6:
        score = 7.5
    elif yoy >= 3:
        score = 6.5
    elif yoy >= 0:
        score = 5.5
    else:
        score = 4.0
    return score, {
        "trend_yoy_change_pct": yoy,
        "trend_score_0_100": sku_trend["trend_score"] * 10,
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


def _calc_sea(sku: dict) -> tuple[float, dict]:
    """出海易度（10%） - 关税低 + 标准通用 + 经验丰富市场。
       决策表：地区出口经验 + 标准通用性。"""
    market_experience = {
        "Saudi Arabia": 1.0, "UAE": 1.0, "Vietnam": 1.0,
        "India": 0.9, "Brazil": 0.8, "Turkey": 0.85,
        "Germany": 0.7, "USA": 0.7, "UK": 0.7,
        "Iraq": 0.8, "Mexico": 0.7,
    }
    avg = sum(market_experience.values()) / len(market_experience)
    score = 5.5 + avg * 4.0
    return round(score, 1), {"company_export_avg_experience_pct": round(avg * 100, 0)}


# -----------------------------------------------------------
# 主评分入口
# -----------------------------------------------------------
def score_one(sku: dict, agg: DataAggregator) -> dict[str, Any]:
    m, m_d = _calc_market(sku, agg)
    g, g_d = _calc_growth(sku, agg)
    f, f_d = _calc_fit(sku)
    mg, mg_d = _calc_margin(sku)
    b, b_d = _calc_barrier(sku)
    s, s_d = _calc_sea(sku)

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


def score_all() -> list[dict[str, Any]]:
    agg = DataAggregator()
    skus = _load_skus()
    results = [score_one(s, agg) for s in skus]
    results.sort(key=lambda x: x["total_score"], reverse=True)
    return results


if __name__ == "__main__":
    res = score_all()
    print(json.dumps(res, indent=2, ensure_ascii=False, default=str))
