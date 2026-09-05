"""
赣丰玻纤 · SEO/GEO 数据引擎（V8 数据飞轮 - 推广引擎）
=====================================================

职责：
  1. 关键词库管理（四层词矩阵：核心词 / 产品词 / 长尾词 / 问答词）
  2. 页面表现追踪（曝光 / 点击 / CTR / 平均排名，按日）
  3. GEO 监测（ChatGPT / Perplexity / AI Overviews 品牌提及）
  4. 自动优化（高曝光低 CTR 页面 → LLM 重写 Title/Meta，失败回退规则模板）
  5. 演示数据种子 + 每日模拟推进（真实 Search Console API 就绪前的驱动器）

表结构见 db.py：seo_keywords / seo_pages / seo_daily / geo_checks /
              seo_optimizations / publish_log
"""
from __future__ import annotations

import json
import logging
import random
import re
from datetime import date, datetime, timedelta
from typing import Any

from db import connect, q  # type: ignore
from llm_client import chat_completion, is_available  # type: ignore

logger = logging.getLogger("seo")

# -----------------------------------------------------------
# 演示种子数据（真实 GSC API 接入前的驾驶舱数据）
# -----------------------------------------------------------
SEED_KEYWORDS: list[dict[str, Any]] = [
    # 核心词
    {"keyword": "fiberglass mesh", "layer": "core", "target_path": "/", "volume_month": 22000, "competition": "high", "rank": 38},
    {"keyword": "alkali resistant fiberglass mesh", "layer": "core", "target_path": "/", "volume_month": 8100, "competition": "high", "rank": 24},
    {"keyword": "fiberglass mesh manufacturer", "layer": "core", "target_path": "/", "volume_month": 6600, "competition": "high", "rank": 31},
    # 产品词
    {"keyword": "fiberglass mesh 145g", "layer": "product", "target_path": "/product/gf-ar-145-44", "volume_month": 2600, "competition": "mid", "rank": 12},
    {"keyword": "self adhesive fiberglass tape", "layer": "product", "target_path": "/product/gf-sa-75-33", "volume_month": 4400, "competition": "mid", "rank": 18},
    {"keyword": "grc mesh 10x10", "layer": "product", "target_path": "/product/gf-grc-150-10", "volume_month": 1900, "competition": "mid", "rank": 15},
    {"keyword": "fiberglass mesh roll 1x50m", "layer": "product", "target_path": "/product/gf-ar-160-55", "volume_month": 2400, "competition": "mid", "rank": 21},
    {"keyword": "waterproofing membrane reinforcement mesh", "layer": "product", "target_path": "/product/gf-wp-160-55", "volume_month": 1300, "competition": "low", "rank": 9},
    {"keyword": "fireproof duct mesh", "layer": "product", "target_path": "/product/gf-fr-200-88", "volume_month": 880, "competition": "low", "rank": 6},
    # 长尾词
    {"keyword": "fiberglass mesh for external wall insulation", "layer": "longtail", "target_path": "/products", "volume_month": 1600, "competition": "low", "rank": 11},
    {"keyword": "fiberglass mesh weight chart", "layer": "longtail", "target_path": "/blog/mesh-weight-guide", "volume_month": 720, "competition": "low", "rank": 5},
    {"keyword": "fiberglass mesh price per square meter", "layer": "longtail", "target_path": "/products", "volume_month": 1100, "competition": "mid", "rank": 17},
    {"keyword": "145g fiberglass mesh price", "layer": "longtail", "target_path": "/product/gf-ar-145-44", "volume_month": 590, "competition": "low", "rank": 7},
    {"keyword": "fiberglass mesh 5x5 vs 4x4", "layer": "longtail", "target_path": "/blog/mesh-size-comparison", "volume_month": 480, "competition": "low", "rank": 8},
    {"keyword": "eifs mesh reinforcement", "layer": "longtail", "target_path": "/product/gf-ar-145-44", "volume_month": 990, "competition": "low", "rank": 10},
    # 问答词
    {"keyword": "how to choose fiberglass mesh", "layer": "qa", "target_path": "/blog/how-to-choose", "volume_month": 390, "competition": "low", "rank": 4},
    {"keyword": "what gram fiberglass mesh for eifs", "layer": "qa", "target_path": "/blog/how-to-choose", "volume_month": 260, "competition": "low", "rank": 3},
    {"keyword": "fiberglass mesh vs pp mesh", "layer": "qa", "target_path": "/blog/mesh-vs-pp", "volume_month": 210, "competition": "low", "rank": 6},
]

SEED_PAGES: list[dict[str, Any]] = [
    {"path": "/", "title": "Ganfeng Fiberglass · Fiberglass Mesh Exporter", "meta_desc": "18 years factory-direct fiberglass mesh. 12 SKU, ISO 9001, free samples, 24h quote.", "base_impr": 260, "ctr": 0.028, "pos": 18.4},
    {"path": "/products", "title": "12 SKU Fiberglass Mesh Product Line | Ganfeng", "meta_desc": "Browse 12 fiberglass mesh SKUs: EWI, waterproofing, GRC, fireproof. Factory prices.", "base_impr": 340, "ctr": 0.021, "pos": 14.2},
    {"path": "/product/gf-ar-145-44", "title": "Fiberglass Mesh 145g 4x4mm | EWI Grade", "meta_desc": "145g alkali-resistant fiberglass mesh for external wall insulation. MOQ 200 rolls.", "base_impr": 420, "ctr": 0.013, "pos": 11.8},
    {"path": "/product/gf-sa-75-33", "title": "Self Adhesive Fiberglass Tape 75g", "meta_desc": "Self-adhesive drywall joint tape 75g. Easy apply, high strength.", "base_impr": 310, "ctr": 0.011, "pos": 13.5},
    {"path": "/product/gf-grc-150-10", "title": "GRC Mesh 10x10 150g | Permanent Formwork", "meta_desc": "GRC reinforcement mesh 10x10mm opening for concrete panels.", "base_impr": 180, "ctr": 0.026, "pos": 9.1},
    {"path": "/product/gf-wp-160-55", "title": "Waterproofing Membrane Mesh 160g", "meta_desc": "160g bitumen membrane reinforcement mesh. Roofing grade.", "base_impr": 150, "ctr": 0.031, "pos": 7.4},
    {"path": "/product/gf-fr-200-88", "title": "Fireproof Duct Mesh 200g", "meta_desc": "200g fire-resistant mesh for HVAC duct wrapping.", "base_impr": 95, "ctr": 0.034, "pos": 6.2},
    {"path": "/product/gf-ar-160-55", "title": "Fiberglass Mesh 160g 5x5mm", "meta_desc": "160g 5x5mm mesh for EIFS base coat reinforcement.", "base_impr": 240, "ctr": 0.012, "pos": 12.6},
    {"path": "/product/gf-hd-280-16", "title": "Heavy Duty Mesh 280g 16x16", "meta_desc": "280g high-strength mesh for floor & road reinforcement.", "base_impr": 120, "ctr": 0.024, "pos": 8.8},
    {"path": "/blog/how-to-choose", "title": "How to Choose Fiberglass Mesh (Gram Guide)", "meta_desc": "45g to 300g: which fiberglass mesh weight fits your application.", "base_impr": 200, "ctr": 0.042, "pos": 4.6},
    {"path": "/blog/mesh-weight-guide", "title": "Fiberglass Mesh Weight Chart | 45g-300g", "meta_desc": "Complete weight chart with tensile strength and applications.", "base_impr": 175, "ctr": 0.038, "pos": 5.1},
    {"path": "/blog/mesh-vs-pp", "title": "Fiberglass Mesh vs PP Mesh: Which Lasts?", "meta_desc": "Alkali resistance comparison between glass and polypropylene mesh.", "base_impr": 90, "ctr": 0.029, "pos": 6.8},
]

GEO_QUESTIONS = [
    "who is a reliable fiberglass mesh manufacturer in China",
    "best alkali resistant fiberglass mesh supplier",
    "fiberglass mesh factory with ISO certification",
    "where to buy fiberglass mesh for EIFS",
    "top fiberglass mesh exporters in Jiangxi",
    "fiberglass mesh manufacturer with free samples",
    "145g fiberglass mesh wholesale supplier",
    "GRC mesh 10x10 manufacturer China",
    "self adhesive fiberglass tape factory",
    "fiberglass mesh price per square meter factory",
]

GEO_ENGINES = ["ChatGPT", "Perplexity", "AI Overviews"]


def _d(days_ago: int) -> str:
    """N 天前的 ISO 日期（跨 SQLite / PostgreSQL）。"""
    return (date.today() - timedelta(days=days_ago)).isoformat()

# 优化队列阈值（V8 方案 ④ SEO 板块规则）
LOW_CTR_THRESHOLD = 0.015      # CTR < 1.5%
HIGH_IMPRESSION_THRESHOLD = 150  # 近 7 天曝光 > 150
OPTIMIZE_COOLDOWN_DAYS = 3


# -----------------------------------------------------------
# 种子 / 初始化
# -----------------------------------------------------------
def ensure_seed(days: int = 30) -> None:
    """仅当 seo_keywords 为空时写入演示数据（幂等）。"""
    with connect() as conn:
        cur = conn.cursor()
        cur.execute("SELECT COUNT(*) FROM seo_keywords")
        if cur.fetchone()[0] > 0:
            return

        today = date.today()
        rng = random.Random(42)

        # 1. 关键词库
        for kw in SEED_KEYWORDS:
            cur.execute(
                q("""INSERT INTO seo_keywords (keyword, layer, target_path, volume_month, competition, rank, status)
                     VALUES (?,?,?,?,?,?,?)"""),
                (kw["keyword"], kw["layer"], kw["target_path"], kw["volume_month"], kw["competition"], kw["rank"], "tracking"),
            )

        # 2. 页面 + 30 天每日数据（带缓慢上升趋势 + 工作日噪声）
        for p in SEED_PAGES:
            cur.execute(
                q("""INSERT INTO seo_pages (path, title, meta_desc, impressions_7d, clicks_7d, avg_position, status)
                     VALUES (?,?,?,?,?,?,?)"""),
                (p["path"], p["title"], p["meta_desc"], 0, 0, p["pos"], "active"),
            )
            for d in range(days - 1, -1, -1):
                day = today - timedelta(days=d)
                growth = 1.0 + (days - d) * 0.012          # 缓慢上升
                weekend = 0.68 if day.weekday() >= 5 else 1.0
                impr = int(p["base_impr"] * growth * weekend * rng.uniform(0.85, 1.15))
                clicks = max(1, int(impr * p["ctr"] * rng.uniform(0.8, 1.25)))
                pos = max(3.0, p["pos"] - (days - d) * 0.05 + rng.uniform(-0.4, 0.4))
                cur.execute(
                    q("""INSERT INTO seo_daily (stat_date, path, impressions, clicks, position)
                         VALUES (?,?,?,?,?)"""),
                    (day.isoformat(), p["path"], impr, clicks, round(pos, 1)),
                )

        # 3. GEO 基线检查（每月一轮 × 3 引擎）
        mentioned_map = {0: [1, 0, 1], 2: [0, 1, 0], 5: [1, 0, 0], 9: [0, 1, 0]}
        for qi, question in enumerate(GEO_QUESTIONS):
            flags = mentioned_map.get(qi, [0, 0, 0])
            for ei, engine in enumerate(GEO_ENGINES):
                cur.execute(
                    q("""INSERT INTO geo_checks (check_date, question, engine, mentioned)
                         VALUES (?,?,?,?)"""),
                    ((today - timedelta(days=20)).isoformat(), question, engine, flags[ei]),
                )

        logger.info("SEO demo data seeded: %d keywords / %d pages / %d days / GEO baseline", len(SEED_KEYWORDS), len(SEED_PAGES), days)


# -----------------------------------------------------------
# 驾驶舱数据聚合
# -----------------------------------------------------------
def _refresh_page_7d(cur: Any) -> None:
    """按近 7 天的 seo_daily 回填 seo_pages 的聚合列。"""
    cutoff = _d(6)
    cur.execute(
        q("""UPDATE seo_pages SET
               impressions_7d = COALESCE((
                   SELECT SUM(impressions) FROM seo_daily sd
                   WHERE sd.path = seo_pages.path
                     AND sd.stat_date >= ?), 0),
               clicks_7d = COALESCE((
                   SELECT SUM(clicks) FROM seo_daily sd
                   WHERE sd.path = seo_pages.path
                     AND sd.stat_date >= ?), 0),
               avg_position = COALESCE((
                   SELECT AVG(position) FROM seo_daily sd
                   WHERE sd.path = seo_pages.path
                     AND sd.stat_date >= ?), avg_position)"""),
        (cutoff, cutoff, cutoff),
    )


def overview() -> dict[str, Any]:
    """SEO/GEO 驾驶舱全量数据。"""
    with connect() as conn:
        cur = conn.cursor()
        _refresh_page_7d(cur)

        # 汇总 KPI（近 7 天 vs 前 7 天）
        cur.execute(
            q("""SELECT
                  SUM(CASE WHEN stat_date >= ? THEN impressions ELSE 0 END),
                  SUM(CASE WHEN stat_date >= ? THEN clicks ELSE 0 END),
                  SUM(CASE WHEN stat_date < ? AND stat_date >= ? THEN impressions ELSE 0 END),
                  SUM(CASE WHEN stat_date < ? AND stat_date >= ? THEN clicks ELSE 0 END),
                  COUNT(DISTINCT CASE WHEN stat_date >= ? THEN stat_date END)
                FROM seo_daily"""),
            (_d(6), _d(6), _d(6), _d(13), _d(6), _d(13), _d(6)),
        )
        impr7, clk7, impr14, clk14, days_cnt = cur.fetchone() or (0, 0, 0, 0, 0)
        impr7, clk7, impr14, clk14 = impr7 or 0, clk7 or 0, impr14 or 0, clk14 or 0
        ctr7 = clk7 / impr7 if impr7 else 0
        ctr14 = clk14 / impr14 if impr14 else 0

        # 日趋势（近 30 天全站汇总）
        cur.execute(
            q("""SELECT stat_date, SUM(impressions), SUM(clicks) FROM seo_daily
                 WHERE stat_date >= ?
                 GROUP BY stat_date ORDER BY stat_date"""),
            (_d(29),),
        )
        trend = [
            {"date": r[0], "impressions": r[1], "clicks": r[2],
             "ctr": round(r[2] / r[1], 4) if r[1] else 0}
            for r in cur.fetchall()
        ]

        # 页面表现（含待优化标记）
        cur.execute(
            q("""SELECT path, title, meta_desc, impressions_7d, clicks_7d, avg_position,
                        status, last_optimized_at
                 FROM seo_pages ORDER BY impressions_7d DESC""")
        )
        pages = []
        for r in cur.fetchall():
            ctr = (r[4] / r[3]) if r[3] else 0
            # 24h 冷却：刚优化过的页面不重复标记/重复优化
            recently_opt = False
            if r[7]:
                try:
                    recently_opt = (datetime.now() - datetime.fromisoformat(str(r[7]))) < timedelta(days=1)
                except ValueError:
                    pass
            needs_opt = r[3] >= HIGH_IMPRESSION_THRESHOLD and ctr < LOW_CTR_THRESHOLD and not recently_opt
            pages.append({
                "path": r[0], "title": r[1], "meta_desc": r[2],
                "impressions": r[3], "clicks": r[4], "ctr": round(ctr, 4),
                "avg_position": round(r[5] or 0, 1),
                "status": r[6],
                "last_optimized": str(r[7])[:16] if r[7] else None,
                "needs_optimization": needs_opt,
            })

        # 关键词表
        cur.execute(
            q("""SELECT keyword, layer, target_path, volume_month, competition, rank, status
                 FROM seo_keywords ORDER BY volume_month DESC""")
        )
        keywords = [
            {"keyword": r[0], "layer": r[1], "target_path": r[2],
             "volume_month": r[3], "competition": r[4], "rank": r[5], "status": r[6]}
            for r in cur.fetchall()
        ]

        # 关键词层分布
        cur.execute(q("SELECT layer, COUNT(*), SUM(volume_month) FROM seo_keywords GROUP BY layer"))
        layer_dist = [{"layer": r[0], "count": r[1], "volume": r[2] or 0} for r in cur.fetchall()]

        # GEO 监测
        cur.execute(
            q("""SELECT check_date, question, engine, mentioned FROM geo_checks
                 WHERE check_date = (SELECT MAX(check_date) FROM geo_checks)
                 ORDER BY question""")
        )
        geo_rows = cur.fetchall()
        geo_questions = []
        mentioned_total = 0
        for r in geo_rows:
            geo_questions.append({"question": r[1], "engine": r[2], "mentioned": bool(r[3])})
            mentioned_total += 1 if r[3] else 0
        geo_mention_rate = round(mentioned_total / len(geo_rows), 3) if geo_rows else 0

        # 优化历史（近 20 条）
        cur.execute(
            q("""SELECT path, field, old_value, new_value, reason, applied_at
                 FROM seo_optimizations ORDER BY id DESC LIMIT 20""")
        )
        history = [
            {"path": r[0], "field": r[1], "old_value": r[2], "new_value": r[3],
             "reason": r[4], "applied_at": str(r[5])[:16]}
            for r in cur.fetchall()
        ]

        # 排名分布：前 3 / 4-10 / 11-20 / 20+
        top3 = sum(1 for k in keywords if k["rank"] and k["rank"] <= 3)
        top10 = sum(1 for k in keywords if k["rank"] and 4 <= k["rank"] <= 10)
        top20 = sum(1 for k in keywords if k["rank"] and 11 <= k["rank"] <= 20)
        beyond = sum(1 for k in keywords if k["rank"] and k["rank"] > 20)

        return {
            "generated_at": datetime.now().isoformat(timespec="seconds"),
            "kpi": {
                "impressions_7d": impr7,
                "clicks_7d": clk7,
                "ctr_7d": round(ctr7, 4),
                "impressions_prev7d": impr14,
                "clicks_prev7d": clk14,
                "ctr_prev7d": round(ctr14, 4),
                "impressions_change": round((impr7 - impr14) / impr14, 3) if impr14 else 0,
                "clicks_change": round((clk7 - clk14) / clk14, 3) if clk14 else 0,
                "ctr_change_pct": round((ctr7 - ctr14) * 100, 2),
                "tracked_keywords": len(keywords),
                "keywords_top10": top3 + top10,
                "pages_tracked": len(pages),
                "pages_need_optimization": sum(1 for p in pages if p["needs_optimization"]),
            },
            "rank_distribution": {"top3": top3, "top4_10": top10, "top11_20": top20, "beyond20": beyond},
            "trend_30d": trend,
            "pages": pages,
            "keywords": keywords,
            "keyword_layers": layer_dist,
            "geo": {
                "questions": geo_questions,
                "mention_rate": geo_mention_rate,
                "engines": GEO_ENGINES,
            },
            "optimization_history": history,
        }


# -----------------------------------------------------------
# 自动优化：高曝光低 CTR 页面 → LLM 重写 Title / Meta
# -----------------------------------------------------------
def _rule_rewrite(page: dict, keywords: list[dict]) -> tuple[str, str, str]:
    """规则模板兜底：把高搜索量关键词前置到 Title。"""
    path = page["path"]
    kw = next((k["keyword"] for k in keywords if k["target_path"] == path and k["layer"] != "qa"), None)
    kw = kw or "Fiberglass Mesh"
    old_title = page["title"]
    # 品牌占位 | 关键词前置
    new_title = f"{kw.title()} | Ganfeng Factory Direct"[:60]
    new_meta = f"{kw.title()} from Ganfeng: 18-yr factory, ISO 9001, free samples, MOQ 200 rolls, 24h quote."[:155]
    return new_title, new_meta, f"规则模板：关键词「{kw}」前置（LLM 不可用降级）"


def _llm_rewrite(page: dict, keywords: list[dict]) -> tuple[str, str, str] | None:
    """LLM 按 SEO 最佳实践重写 Title/Meta。"""
    target_kws = [k["keyword"] for k in keywords if k["target_path"] == page["path"]][:5]
    if not target_kws:
        target_kws = ["fiberglass mesh"]
    prompt = f"""你是 SEO 专家。为玻纤网格布外贸独立站页面重写 Title 和 Meta Description。

页面路径: {page['path']}
当前 Title: {page['title']}
当前 Meta: {page['meta_desc']}
近7天: 曝光 {page['impressions']}，CTR {page['ctr']*100:.1f}%（偏低），平均排名 {page['avg_position']}
目标关键词: {', '.join(target_kws)}

要求：
1. Title ≤ 60 字符，主关键词放最前面，带吸引点击的卖点（Factory Direct / Free Sample 等）
2. Meta ≤ 155 字符，包含关键词 + 行动号召
3. 不堆砌关键词，符合 Google 规范

只输出 JSON：{{"title":"...","meta_desc":"..."}}"""
    try:
        raw = chat_completion(
            [{"role": "system", "content": "你是资深英文 SEO 文案。只输出 JSON。"},
             {"role": "user", "content": prompt}],
            temperature=0.4, max_tokens=300,
        )
        if not raw:
            return None
        clean = raw.strip()
        if clean.startswith("```"):
            clean = clean.split("\n", 1)[1] if "\n" in clean else clean[3:]
        if clean.endswith("```"):
            clean = clean.rsplit("```", 1)[0]
        obj = json.loads(clean.strip())
        title, meta = obj.get("title", ""), obj.get("meta_desc", "")
        if title and meta:
            return title[:60], meta[:155], f"LLM 重写（目标词: {', '.join(target_kws[:2])}）"
    except Exception as e:
        logger.warning("LLM rewrite failed: %s", e)
    return None


def auto_optimize(max_pages: int = 3) -> dict[str, Any]:
    """执行一轮自动优化，返回优化清单（V8 闭环第 ③ 步）。"""
    data = overview()
    keywords = data["keywords"]
    targets = [p for p in data["pages"] if p["needs_optimization"]][:max_pages]

    results = []
    with connect() as conn:
        cur = conn.cursor()
        for page in targets:
            rewrite = _llm_rewrite(page, keywords) if is_available() else None
            if rewrite is None:
                rewrite = _rule_rewrite(page, keywords)
            new_title, new_meta, reason = rewrite
            if new_title == page["title"] and new_meta == page["meta_desc"]:
                continue

            now = datetime.now().isoformat(timespec="seconds")
            for field, old_v, new_v in (("title", page["title"], new_title), ("meta_desc", page["meta_desc"], new_meta)):
                cur.execute(
                    q("""INSERT INTO seo_optimizations (path, field, old_value, new_value, reason, applied_at)
                         VALUES (?,?,?,?,?,?)"""),
                    (page["path"], field, old_v, new_v, reason, now),
                )
            cur.execute(
                q("""UPDATE seo_pages SET title = ?, meta_desc = ?, last_optimized_at = ?
                     WHERE path = ?"""),
                (new_title, new_meta, now, page["path"]),
            )
            # 优化后模拟排名/CTR 温和改善（排名 + CTR 双提升，CTR 逐步脱离低点击阈值）
            cur.execute(
                q("""UPDATE seo_daily SET position = CASE
                         WHEN position * 0.97 < 2.0 THEN 2.0 ELSE position * 0.97 END
                     WHERE path = ? AND stat_date >= ?"""),
                (page["path"], _d(1)),
            )
            cur.execute(
                q("UPDATE seo_daily SET clicks = CAST(clicks * 1.35 AS INTEGER) + 1 WHERE path = ? AND stat_date >= ?"),
                (page["path"], _d(6)),
            )
            results.append({
                "path": page["path"],
                "old_title": page["title"], "new_title": new_title,
                "old_meta": page["meta_desc"], "new_meta": new_meta,
                "reason": reason,
                "engine": "LLM (DeepSeek)" if is_available() else "Rule fallback",
            })

    return {
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "candidates": sum(1 for p in data["pages"] if p["needs_optimization"]),
        "optimized": len(results),
        "details": results,
    }


# -----------------------------------------------------------
# 每日模拟推进（真实 GSC API 就绪前的数据驱动器）
# -----------------------------------------------------------
def simulate_day() -> dict[str, Any]:
    """推进一天：生成新的每日数据 + 当日 GEO 抽查。对应闭环第 ① 步。"""
    rng = random.Random()
    today = date.today()
    added = 0
    with connect() as conn:
        cur = conn.cursor()
        cur.execute(q("SELECT path, title, meta_desc FROM seo_pages"))
        pages = cur.fetchall()
        cur.execute(q("SELECT COUNT(*) FROM seo_daily WHERE stat_date = ?"), (today.isoformat(),))
        if cur.fetchone()[0] > 0:
            # 当天已有数据：清除当日数据后重新生成，支持演示中多次点击「模拟推进一天」
            cur.execute(q("DELETE FROM seo_daily WHERE stat_date = ?"), (today.isoformat(),))
            cur.execute(q("DELETE FROM geo_checks WHERE check_date = ?"), (today.isoformat(),))

        for path, _title, _meta in pages:
            cur.execute(
                q("""SELECT AVG(impressions), AVG(clicks) FROM seo_daily
                     WHERE path = ? AND stat_date >= ?"""),
                (path, _d(6)),
            )
            avg_i, avg_c = cur.fetchone() or (0, 0)
            base_i = float(avg_i or 150)  # PG 的 AVG 返回 Decimal，需转 float
            impr = int(base_i * rng.uniform(0.9, 1.15) * (0.7 if today.weekday() >= 5 else 1.0))
            clicks = max(1, int(impr * rng.uniform(0.012, 0.03)))
            cur.execute(
                q("""SELECT AVG(position) FROM seo_daily
                     WHERE path = ? AND stat_date >= ?"""),
                (path, _d(6)),
            )
            prev_pos = float(cur.fetchone()[0] or 15.0)  # 同上，Decimal → float
            pos = max(2.0, prev_pos * rng.uniform(0.96, 1.0))  # 缓慢改善
            cur.execute(
                q("""INSERT INTO seo_daily (stat_date, path, impressions, clicks, position)
                     VALUES (?,?,?,?,?)"""),
                (today.isoformat(), path, impr, clicks, round(pos, 1)),
            )
            added += 1

        # GEO 当日抽查一个问题 × 3 引擎
        cur.execute(q("SELECT COUNT(DISTINCT question) FROM geo_checks"))
        total_q = cur.fetchone()[0] or len(GEO_QUESTIONS)
        pick = GEO_QUESTIONS[rng.randrange(min(len(GEO_QUESTIONS), max(total_q, 1)))]
        for engine in GEO_ENGINES:
            cur.execute(
                q("""INSERT INTO geo_checks (check_date, question, engine, mentioned)
                     VALUES (?,?,?,?)"""),
                (today.isoformat(), pick, engine, 1 if rng.random() < 0.3 else 0),
            )

        _refresh_page_7d(cur)  # 刷新 seo_pages 的 7 天汇总
    return {"status": "ok", "date": today.isoformat(), "pages_added": added}


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    ensure_seed()
    data = overview()
    print(json.dumps(data["kpi"], ensure_ascii=False, indent=2))
    print("need optimization:", [p["path"] for p in data["pages"] if p["needs_optimization"]])
