"""
赣丰玻纤 · 数据飞轮系统主程序
==============================

基于 V5 实施路线图，按以下架构实现：

  前端独立站 (/)               ← 产品展示 / 询盘表单 / 客服入口
      ↕ ajax
  Flask 后端 (本文件)
   ├── /api/inquiry  询盘提交
   ├── /api/chat     智能客服
   ├── /api/sourcing 选品评分
   ├── /api/products 产品清单
   ├── /api/customer-count 询盘统计
   └── /             管理后台

数据层：
  - PostgreSQL（设置 DATABASE_URL 时）/ SQLite（本地开发）
  - 飞书多维表格（真实 Open API，见 scripts/feishu_client.py）
  - 免费数据源（Comtrade / WITS / World Bank / Google Trends 真实接入）
"""
from __future__ import annotations
import json
import logging
import os
import sys
import threading
import uuid
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / "scripts"))

from flask import Flask, request, jsonify, render_template  # type: ignore

from db import connect, q, insert_returning_id, backend_name  # type: ignore
from init_db import bootstrap  # type: ignore
from sourcing_engine import score_all  # type: ignore
from chatbot_engine import ChatbotEngine  # type: ignore
from free_data_sources import DataAggregator  # type: ignore
from feishu_sync import FeishuSync  # type: ignore
import feishu_client  # type: ignore
import seo_engine  # type: ignore
import chat_analytics  # type: ignore

logging.basicConfig(
    level=os.environ.get("LOG_LEVEL", "INFO"),
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
)
log = logging.getLogger("app")

app = Flask(
    __name__,
    template_folder=str(ROOT / "templates"),
    static_folder=str(ROOT / "static"),
)

# 启动前初始化数据库
log.info("[boot] initializing database backend=%s ...", backend_name())
bootstrap(seed=os.environ.get("SEED_SAMPLES", "true").lower() == "true")
log.info("[boot] database ready")


# ============================================================
# 页面路由
# ============================================================
@app.route("/")
def page_home():
    return render_template("index.html")


@app.route("/admin")
def page_admin():
    return render_template("admin.html")


@app.route("/robots.txt")
def robots():
    return "User-agent: *\nAllow: /\n", 200, {"Content-Type": "text/plain"}


# ============================================================
# API
# ============================================================
@app.route("/api/products", methods=["GET"])
def api_products():
    """产品列表 - 主页/独立站展示用（管理后台一键发布后：推荐 SKU 置顶）"""
    lang = request.args.get("lang", "zh")
    with open(ROOT / "data" / "sku.json", "r", encoding="utf-8") as f:
        data = json.load(f)
    products = data["products"]
    company = data["company"]

    # 合并数据库中的「推荐置顶」状态（一键选品发布的落点）
    featured_map: dict[str, int] = {}
    try:
        with connect() as conn:
            cur = conn.cursor()
            cur.execute(q("SELECT sku, featured_rank FROM products WHERE featured = 1"))
            featured_map = {r[0]: (r[1] or 999) for r in cur.fetchall()}
    except Exception as e:
        log.warning("featured query failed: %s", e)

    out = []
    for p in products:
        out.append({
            "sku": p["sku"],
            "name": p["name_zh"] if lang == "zh" else p["name_en"],
            "name_zh": p["name_zh"],
            "name_en": p["name_en"],
            "gram": p.get("gram"),
            "mesh_size": p.get("mesh_size"),
            "width": p.get("width"),
            "length_per_roll": p.get("length_per_roll"),
            "tensile_strength_warp": p.get("tensile_strength_warp_N_50mm"),
            "tensile_strength_weft": p.get("tensile_strength_weft_N_50mm"),
            "alkali_resistance_pct": p.get("alkali_resistance_pct"),
            "applications": p.get("applications", []),
            "scenarios": p.get("scenarios", []),
            "moq_rolls": p.get("moq_rolls"),
            "lead_time_days": p.get("lead_time_days"),
            "unit_cost_cny": p.get("unit_cost_cny"),
            "target_price_usd_per_sqm": p.get("target_price_usd_per_sqm"),
            "featured": p["sku"] in featured_map,
            "featured_rank": featured_map.get(p["sku"]),
        })

    # 推荐 SKU 置顶（featured_rank 升序），其余保持原顺序
    out.sort(key=lambda x: x["featured_rank"] if x["featured"] else 1000)
    return jsonify({"company": company, "products": out})


@app.route("/api/inquiry", methods=["POST"])
def api_inquiry():
    """询盘提交：写入 SQLite + 自动触发飞书自动化（演示：dry-run 打印）"""
    payload = request.get_json() or {}
    required = ["name", "email"]
    for k in required:
        if not payload.get(k):
            return jsonify({"status": "error", "msg": f"missing field: {k}"}), 400

    try:
        with connect() as conn:
            cur = conn.cursor()
            # 1. 写入客户
            customer_id = insert_returning_id(
                cur,
                """INSERT INTO customers (name, company, country, email, phone, intent)
                   VALUES (?,?,?,?,?,?)""",
                (
                    payload.get("name", ""),
                    payload.get("company", ""),
                    payload.get("country", ""),
                    payload.get("email", ""),
                    payload.get("phone", ""),
                    payload.get("intent", "rfq"),
                ),
            )

            # 2. 写入询盘
            inquiry_id = insert_returning_id(
                cur,
                """INSERT INTO inquiries
                   (customer_id, sku, quantity_rolls, quantity_sqm, message, source)
                   VALUES (?,?,?,?,?,?)""",
                (
                    customer_id,
                    payload.get("sku"),
                    payload.get("quantity_rolls"),
                    payload.get("quantity_sqm"),
                    payload.get("message", ""),
                    payload.get("source", "website"),
                ),
            )
    except Exception as e:
        log.exception("inquiry insert failed")
        return jsonify({"status": "error", "msg": str(e)}), 500

    # 3. 同步飞书 + 群通知（失败不影响询盘落库）
    record = {
        "inquiry_id": inquiry_id,
        "customer_id": customer_id,
        "customer": payload.get("name"),
        "company": payload.get("company"),
        "country": payload.get("country"),
        "email": payload.get("email"),
        "phone": payload.get("phone"),
        "sku": payload.get("sku"),
        "qty": payload.get("quantity_rolls"),
        "quantity_sqm": payload.get("quantity_sqm"),
        "message": payload.get("message", ""),
        "source": payload.get("source", "website"),
        "intent": payload.get("intent", "rfq"),
    }
    try:
        result = FeishuSync().trigger_automation("new_inquiry", record)
        action, status = result.get("action", "feishu"), result.get("status", "unknown")
    except Exception as e:
        log.warning("feishu automation failed: %s", e)
        action, status = "feishu-notify", f"error: {e}"

    # 4. 记录自动化日志
    try:
        with connect() as conn:
            cur = conn.cursor()
            cur.execute(
                q("""INSERT INTO automation_log
                     (trigger_type, trigger_payload, action_taken, status)
                     VALUES (?,?,?,?)"""),
                ("new_inquiry", json.dumps(record, ensure_ascii=False), action, status),
            )
    except Exception as e:
        log.warning("automation_log write failed: %s", e)

    return jsonify({
        "status": "ok",
        "inquiry_id": inquiry_id,
        "customer_id": customer_id,
        "feishu": status,
        "msg": "感谢您的询盘！我们将在 24h 内回复。 / Inquiry received! We'll reply within 24h.",
    })


@app.route("/api/chat", methods=["POST"])
def api_chat():
    """智能客服入口"""
    payload = request.get_json() or {}
    msg = (payload.get("message") or "").strip()
    session_id = payload.get("session_id") or uuid.uuid4().hex[:12]
    if not msg:
        return jsonify({"status": "error", "msg": "empty message"}), 400

    eng = ChatbotEngine()
    out = eng.reply(msg, session_id, lang=payload.get("lang"))

    # 写入对话日志（日志失败不影响回复返回）
    try:
        with connect() as conn:
            cur = conn.cursor()
            sql = q("INSERT INTO chat_logs (session_id, message, role, intent) VALUES (?,?,?,?)")
            cur.execute(sql, (session_id, msg, "user", out["intent"]))
            cur.execute(sql, (session_id, out["text"], "bot", out["intent"]))
    except Exception as e:
        log.warning("chat_log write failed: %s", e)

    return jsonify({"session_id": session_id, "reply": out})


SOURCING_CACHE_KEY = "sourcing_result"
SOURCING_TTL = int(os.environ.get("SOURCING_TTL", str(6 * 3600)))


@app.route("/api/sourcing", methods=["GET"])
def api_sourcing():
    """选品评分结果（缓存在 data_cache 表，容器重启不丢）"""
    from db import cache_get, cache_put  # 局部导入避免循环

    if request.args.get("refresh", "0") != "1":
        hit = cache_get(SOURCING_CACHE_KEY, SOURCING_TTL)
        if hit:
            hit["cached"] = True
            return jsonify(hit)

    res = score_all()
    out = {
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "weights": {"market": 0.25, "growth": 0.20, "fit": 0.20,
                    "margin": 0.15, "barrier": 0.10, "sea": 0.10},
        "scores": res,
        "cached": False,
    }

    try:
        with connect() as conn:
            cur = conn.cursor()
            for r in res:
                d = r["dimensions"]
                cur.execute(
                    q("""INSERT INTO sourcing_scores
                         (sku, score_total, score_market, score_growth, score_fit,
                          score_margin, score_barrier, score_sea, tier,
                          recommend_actions, ai_reason, target_market)
                         VALUES (?,?,?,?,?,?,?,?,?,?,?,?)"""),
                    (
                        r["sku"], r["total_score"],
                        d["market"]["score"], d["growth"]["score"], d["fit"]["score"],
                        d["margin"]["score"], d["barrier"]["score"], d["sea"]["score"],
                        r["tier"],
                        json.dumps(r["recommend_actions"], ensure_ascii=False),
                        r.get("ai_reason"), r.get("target_market"),
                    ),
                )
    except Exception as e:
        log.warning("sourcing_scores write failed: %s", e)

    cache_put(SOURCING_CACHE_KEY, out, "ok")
    return jsonify(out)


# ── 数据源状态 ───────────────────────────────────
_refresh_lock = threading.Lock()
_refreshing = {"active": False, "started_at": None}


def _background_refresh(force: bool = True):
    """后台线程里做真实抓取。Comtrade/WITS 有限流，全量需数分钟。"""
    try:
        from free_data_sources import refresh_all, warm_up  # type: ignore

        summary = refresh_all() if force else warm_up()
        log.info("data source refresh finished: %s", summary)
    except Exception as e:
        log.warning("data source refresh failed: %s", e)
    finally:
        with _refresh_lock:
            _refreshing["active"] = False


def _start_refresh(force: bool = True) -> bool:
    with _refresh_lock:
        if _refreshing["active"]:
            return False
        _refreshing["active"] = True
        _refreshing["started_at"] = datetime.now().isoformat(timespec="seconds")
    threading.Thread(target=_background_refresh, args=(force,), daemon=True).start()
    return True


@app.route("/api/data-sources", methods=["GET"])
def api_data_sources():
    """免费数据源聚合结果。

    ?refresh=1 触发后台强制刷新（Comtrade 有速率限制，全量刷新需数分钟，
    因此立即返回当前缓存，不阻塞请求）。
    """
    if request.args.get("refresh", "0") == "1":
        started = _start_refresh(force=True)
        res = DataAggregator().fetch_all()
        res["refresh"] = {
            "triggered": started,
            "note": "后台刷新中，Comtrade 速率限制下约需 3-5 分钟，稍后重新查询",
            "started_at": _refreshing["started_at"],
        }
        return jsonify(res)

    return jsonify(DataAggregator().fetch_all())


def _boot_warm_up():
    """启动后在后台补齐冷缓存，不阻塞第一个请求。"""
    if os.environ.get("WARM_UP_ON_BOOT", "true").lower() != "true":
        return
    from db import cache_status  # type: ignore

    try:
        known = {c["source"] for c in cache_status()}
    except Exception:
        known = set()
    agg = DataAggregator()
    needed = {a.name for a in (agg.comtrade, agg.wits, agg.worldbank, agg.trends)}
    if needed - known:
        log.info("[boot] 数据源缓存缺失 %s，后台预热中", sorted(needed - known))
        _start_refresh(force=False)


_boot_warm_up()


@app.route("/api/data-sources/status", methods=["GET"])
def api_data_sources_status():
    """轻量状态查询：只读缓存元信息，不触发任何外部请求。"""
    from db import cache_status  # 局部导入避免循环

    return jsonify({
        "backend": backend_name(),
        "refreshing": _refreshing["active"],
        "caches": cache_status(),
    })


# ── 飞书 ─────────────────────────────────────────
@app.route("/api/feishu/ping", methods=["GET"])
def api_feishu_ping():
    """飞书配置自检：token 能否获取、多维表格能否访问。"""
    return jsonify(feishu_client.get_client().ping())


@app.route("/api/feishu/chats", methods=["GET"])
def api_feishu_chats():
    """列出机器人所在的群，用来查 LARK_CHAT_ID。"""
    try:
        return jsonify({"status": "ok", "chats": feishu_client.get_client().list_chats()})
    except Exception as e:
        return jsonify({"status": "error", "msg": str(e),
                        "hint": "需要在飞书后台为应用开通 im:chat:readonly 权限"}), 400


@app.route("/api/feishu/setup", methods=["POST"])
def api_feishu_setup():
    """在多维表格中创建 V5 方案要求的 5 张表（幂等，已存在则跳过）。"""
    try:
        return jsonify(feishu_client.get_client().ensure_tables())
    except Exception as e:
        return jsonify({"status": "error", "msg": str(e)}), 400


@app.route("/api/feishu/sync", methods=["POST"])
def api_feishu_sync():
    """把本地库的产品/客户/询盘/选品结果全量同步到飞书多维表格。"""
    try:
        return jsonify(FeishuSync().sync_all())
    except Exception as e:
        log.exception("feishu sync failed")
        return jsonify({"status": "error", "msg": str(e)}), 400


@app.route("/api/dashboard", methods=["GET"])
def api_dashboard():
    """管理后台用的统计接口"""
    def one(cur, sql: str) -> int:
        cur.execute(sql)
        return int(cur.fetchone()[0])

    with connect() as conn:
        cur = conn.cursor()
        stats = {
            "total_customers": one(cur, "SELECT COUNT(*) FROM customers"),
            "total_inquiries": one(cur, "SELECT COUNT(*) FROM inquiries"),
            "new_inquiries": one(cur, "SELECT COUNT(*) FROM inquiries WHERE status='new'"),
            "total_chats": one(cur, "SELECT COUNT(*) FROM chat_logs"),
        }
        cur.execute(
            """SELECT i.id, c.name, c.country, i.sku, i.quantity_rolls, i.status, i.created_at
               FROM inquiries i LEFT JOIN customers c ON i.customer_id = c.id
               ORDER BY i.id DESC LIMIT 10"""
        )
        recent_inq = [
            {
                "id": r[0], "customer": r[1], "country": r[2], "sku": r[3],
                "qty": r[4], "status": r[5], "created_at": str(r[6])[:19],
            }
            for r in cur.fetchall()
        ]
        cur.execute(
            """SELECT c.country, COUNT(*) FROM inquiries i
               JOIN customers c ON i.customer_id = c.id
               GROUP BY c.country ORDER BY 2 DESC"""
        )
        countries = cur.fetchall()

    return jsonify({
        "stats": stats,
        "recent_inquiries": recent_inq,
        "country_distribution": [{"country": c or "未知", "count": n} for c, n in countries],
    })


# ============================================================
# 管理后台 · 三大数据分析模块 API（V8）
# ============================================================
def _latest_scores() -> list[dict]:
    """取最新一轮选品评分（缓存 → DB → 现算，逐级降级）。"""
    from db import cache_get  # 局部导入避免循环

    cached = cache_get(SOURCING_CACHE_KEY, SOURCING_TTL * 10)
    if cached and cached.get("scores"):
        return cached["scores"]
    try:
        with connect() as conn:
            cur = conn.cursor()
            cur.execute(
                q("""SELECT sku, score_total, tier, ai_reason, target_market, fetched_at
                     FROM sourcing_scores ss
                     WHERE id = (SELECT MAX(id) FROM sourcing_scores s2 WHERE s2.sku = ss.sku)
                     ORDER BY score_total DESC""")
            )
            rows = cur.fetchall()
        if rows:
            return [
                {"sku": r[0], "total_score": r[1], "tier": r[2],
                 "ai_reason": r[3], "target_market": r[4]}
                for r in rows
            ]
    except Exception as e:
        log.warning("latest scores query failed: %s", e)
    return score_all()


@app.route("/api/admin/sourcing-analysis", methods=["GET"])
def api_admin_sourcing_analysis():
    """模块一：选品数据分析 + 选品建议 + 当前发布状态。"""
    scores = _latest_scores()

    # 维度聚合（从 DB 取每 SKU 最新一轮的 6 维）
    dimension_avg = {"market": 0, "growth": 0, "fit": 0, "margin": 0, "barrier": 0, "sea": 0}
    dim_count = 0
    try:
        with connect() as conn:
            cur = conn.cursor()
            cur.execute(
                q("""SELECT AVG(score_market), AVG(score_growth), AVG(score_fit),
                            AVG(score_margin), AVG(score_barrier), AVG(score_sea), COUNT(DISTINCT sku)
                     FROM sourcing_scores ss
                     WHERE id = (SELECT MAX(id) FROM sourcing_scores s2 WHERE s2.sku = ss.sku)""")
            )
            r = cur.fetchone()
            if r and r[6]:
                dimension_avg = {
                    "market": round(r[0] or 0, 2), "growth": round(r[1] or 0, 2),
                    "fit": round(r[2] or 0, 2), "margin": round(r[3] or 0, 2),
                    "barrier": round(r[4] or 0, 2), "sea": round(r[5] or 0, 2),
                }
                dim_count = r[6]

            # 评分趋势（按天平均总分）
            cur.execute(
                q("""SELECT SUBSTR(fetched_at, 1, 10) AS d, AVG(score_total)
                     FROM sourcing_scores GROUP BY d ORDER BY d DESC LIMIT 14""")
            )
            trend = [{"date": r[0], "avg_score": round(r[1], 2)} for r in cur.fetchall()][::-1]

            # 当前推荐位 + 发布日志
            cur.execute(q("SELECT sku FROM products WHERE featured = 1 ORDER BY featured_rank"))
            featured = [r[0] for r in cur.fetchall()]
            cur.execute(q("SELECT skus, trigger, detail, created_at FROM publish_log ORDER BY id DESC LIMIT 5"))
            pub_log = [
                {"skus": json.loads(r[0] or "[]"), "trigger": r[1],
                 "detail": json.loads(r[2] or "{}"), "created_at": str(r[3])[:16]}
                for r in cur.fetchall()
            ]
    except Exception as e:
        log.warning("sourcing analysis agg failed: %s", e)
        trend, featured, pub_log = [], [], []

    # 规则化选品建议（数据飞轮输出）
    t1 = [s for s in scores if s["tier"] == "T1"]
    t2 = [s for s in scores if s["tier"] == "T2"]
    suggestions = []
    if t1:
        suggestions.append(f"T1 主推 SKU {len(t1)} 款：{', '.join(s['sku'] for s in t1[:3])} — 建议立即置顶到独立站首页")
    if t2:
        suggestions.append(f"T2 备选 {len(t2)} 款 — 建议配套 1-2 个重点市场做样品推广")
    weak_margin = dimension_avg["margin"] < 6.0
    if weak_margin:
        suggestions.append("毛利率维度整体偏弱 — 建议对低毛利 SKU 谈原料集采或小幅提价 2-3%")
    if not featured:
        suggestions.append("首页推荐位为空 — 点击「一键发布 Top SKU」把高评分产品推到独立站首页")

    tier_dist = {"T1": len(t1), "T2": len(t2),
                 "T3": len(scores) - len(t1) - len(t2) - sum(1 for s in scores if s["tier"] == "T4"),
                 "T4": sum(1 for s in scores if s["tier"] == "T4")}

    return jsonify({
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "scores": scores,
        "tier_distribution": tier_dist,
        "dimension_avg": dimension_avg,
        "dimension_sample_count": dim_count,
        "score_trend": trend,
        "featured_skus": featured,
        "publish_log": pub_log,
        "suggestions": suggestions,
    })


@app.route("/api/admin/publish-products", methods=["POST"])
def api_admin_publish_products():
    """模块一：一键选品更新到网页（Top SKU 置顶独立站首页）。"""
    payload = request.get_json() or {}
    count = min(int(payload.get("count", 6)), 12)
    skus = payload.get("skus")

    if not skus:
        scores = _latest_scores()
        skus = [s["sku"] for s in scores[:count]]
    if not skus:
        return jsonify({"status": "error", "msg": "no skus to publish"}), 400

    try:
        with connect() as conn:
            cur = conn.cursor()
            cur.execute(q("UPDATE products SET featured = 0, featured_rank = NULL"))
            for rank, sku in enumerate(skus, start=1):
                cur.execute(
                    q("UPDATE products SET featured = 1, featured_rank = ? WHERE sku = ?"),
                    (rank, sku),
                )
            cur.execute(
                q("""INSERT INTO publish_log (skus, trigger, detail)
                     VALUES (?,?,?)"""),
                (json.dumps(skus, ensure_ascii=False), payload.get("trigger", "manual"),
                 json.dumps({"count": len(skus)}, ensure_ascii=False)),
            )
    except Exception as e:
        log.exception("publish failed")
        return jsonify({"status": "error", "msg": str(e)}), 500

    return jsonify({
        "status": "ok",
        "published": skus,
        "msg": f"已把 {len(skus)} 款 SKU 推送到独立站首页推荐位（置顶显示）",
    })


@app.route("/api/admin/seo/overview", methods=["GET"])
def api_admin_seo_overview():
    """模块二：SEO/GEO 推广数据驾驶舱。"""
    return jsonify(seo_engine.overview())


@app.route("/api/admin/seo/optimize", methods=["POST"])
def api_admin_seo_optimize():
    """模块二：执行一轮自动优化（高曝光低 CTR 页面重写 Title/Meta）。"""
    try:
        return jsonify(seo_engine.auto_optimize(max_pages=3))
    except Exception as e:
        log.exception("seo optimize failed")
        return jsonify({"status": "error", "msg": str(e)}), 500


@app.route("/api/admin/seo/simulate-day", methods=["POST"])
def api_admin_seo_simulate():
    """模块二：模拟推进一天数据（真实 Search Console API 就绪前的驱动器）。"""
    try:
        return jsonify(seo_engine.simulate_day())
    except Exception as e:
        log.exception("seo simulate failed")
        return jsonify({"status": "error", "msg": str(e)}), 500


@app.route("/api/admin/chat/analytics", methods=["GET"])
def api_admin_chat_analytics():
    """模块三：智能客服全量数据分析。"""
    return jsonify(chat_analytics.analytics())


@app.route("/api/admin/chat/session/<session_id>", methods=["GET"])
def api_admin_chat_session(session_id: str):
    """模块三：单个会话完整对话记录。"""
    detail = chat_analytics.session_detail(session_id)
    if not detail["messages"]:
        return jsonify({"status": "error", "msg": "session not found"}), 404
    return jsonify(detail)


@app.route("/api/health")
def health():
    """健康检查：同时探测数据库真实可用性。"""
    db_ok, db_err = True, None
    try:
        with connect() as conn:
            conn.cursor().execute("SELECT 1")
    except Exception as e:
        db_ok, db_err = False, str(e)[:200]

    from llm_client import is_available  # type: ignore

    body = {
        "status": "ok" if db_ok else "degraded",
        "ts": datetime.now().isoformat(timespec="seconds"),
        "db": {"backend": backend_name(), "ok": db_ok, "error": db_err},
        "llm": {"provider": "deepseek", "configured": is_available()},
        "feishu": {"configured": feishu_client.is_configured(),
                   "dry_run": feishu_client.is_dry_run()},
    }
    return jsonify(body), (200 if db_ok else 503)


# ============================================================
# 错误处理
# ============================================================
@app.errorhandler(404)
def not_found(e):
    if request.path.startswith("/api/"):
        return jsonify({"status": "error", "msg": "not found"}), 404
    return render_template("index.html"), 200


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "5000"))
    print(f"\n🚀 赣丰玻纤数据飞轮系统启动")
    print(f"   📍 独立站:       http://127.0.0.1:{port}/")
    print(f"   📊 管理后台:     http://127.0.0.1:{port}/admin")
    print(f"   🤖 AI 客服 API:  POST http://127.0.0.1:{port}/api/chat")
    print(f"   📋 询盘 API:     POST http://127.0.0.1:{port}/api/inquiry")
    print(f"   🌟 选品 API:     GET  http://127.0.0.1:{port}/api/sourcing")
    print(f"   🌐 数据源:       GET  http://127.0.0.1:{port}/api/data-sources")
    print(f"   🔗 飞书自检:     GET  http://127.0.0.1:{port}/api/feishu/ping")
    print(f"   📦 数据库:       {backend_name()}\n")
    app.run(host="0.0.0.0", port=port, debug=False)
