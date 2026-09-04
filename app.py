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
  - SQLite 本地（演示用）
  - 飞书多维表格（同结构字段，待 lark-base 接入）
  - 免费数据源（Comtrade/Trends/WITS mock + 真实接入接口）
"""
from __future__ import annotations
import json
import os
import sqlite3
import sys
import uuid
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / "scripts"))

from flask import Flask, request, jsonify, render_template, send_from_directory  # type: ignore

from init_db import init_db, insert_sample_data, DB_FILE  # type: ignore
from sourcing_engine import score_all  # type: ignore
from chatbot_engine import ChatbotEngine  # type: ignore
from free_data_sources import DataAggregator  # type: ignore
from feishu_sync import FeishuSync  # type: ignore

app = Flask(
    __name__,
    template_folder=str(ROOT / "templates"),
    static_folder=str(ROOT / "static"),
)


# 启动前初始化数据库
print("[boot] initializing SQLite...")
_conn = init_db(DB_FILE)
insert_sample_data(_conn)
print("[boot] OK")


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
    """产品列表 - 主页/独立站展示用"""
    lang = request.args.get("lang", "zh")
    with open(ROOT / "data" / "sku.json", "r", encoding="utf-8") as f:
        data = json.load(f)
    products = data["products"]
    company = data["company"]
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
        })
    return jsonify({"company": company, "products": out})


@app.route("/api/inquiry", methods=["POST"])
def api_inquiry():
    """询盘提交：写入 SQLite + 自动触发飞书自动化（演示：dry-run 打印）"""
    payload = request.get_json() or {}
    required = ["name", "email"]
    for k in required:
        if not payload.get(k):
            return jsonify({"status": "error", "msg": f"missing field: {k}"}), 400

    conn = sqlite3.connect(DB_FILE)
    cur = conn.cursor()
    try:
        # 1. 写入客户
        cur.execute(
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
        customer_id = cur.lastrowid

        # 2. 写入询盘
        cur.execute(
            """INSERT INTO inquiries (customer_id, sku, quantity_rolls, quantity_sqm, message, source)
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
        inquiry_id = cur.lastrowid
        conn.commit()

        # 3. 触发飞书自动化
        fsync = FeishuSync(DB_FILE, dry_run=True)
        fsync.trigger_automation(
            "new_inquiry",
            {
                "inquiry_id": inquiry_id,
                "customer": payload.get("name"),
                "country": payload.get("country"),
                "sku": payload.get("sku"),
                "qty": payload.get("quantity_rolls"),
            },
        )

        # 4. 记录自动化日志
        cur.execute(
            "INSERT INTO automation_log (trigger_type, trigger_payload, action_taken, status) VALUES (?,?,?,?)",
            ("new_inquiry", json.dumps(payload), "feishu-dry-run-notify", "sent"),
        )
        conn.commit()

        return jsonify({
            "status": "ok",
            "inquiry_id": inquiry_id,
            "customer_id": customer_id,
            "msg": "感谢您的询盘！我们将在 24h 内回复。 / Inquiry received! We'll reply within 24h.",
        })
    except Exception as e:
        conn.rollback()
        return jsonify({"status": "error", "msg": str(e)}), 500
    finally:
        conn.close()


@app.route("/api/chat", methods=["POST"])
def api_chat():
    """智能客服入口"""
    payload = request.get_json() or {}
    msg = (payload.get("message") or "").strip()
    session_id = payload.get("session_id") or uuid.uuid4().hex[:12]
    if not msg:
        return jsonify({"status": "error", "msg": "empty message"}), 400

    eng = ChatbotEngine()
    out = eng.reply(msg, session_id)

    # 写入对话日志
    conn = sqlite3.connect(DB_FILE)
    cur = conn.cursor()
    try:
        cur.execute(
            "INSERT INTO chat_logs (session_id, message, role, intent) VALUES (?,?,?,?)",
            (session_id, msg, "user", out["intent"]),
        )
        cur.execute(
            "INSERT INTO chat_logs (session_id, message, role, intent) VALUES (?,?,?,?)",
            (session_id, out["text"], "bot", out["intent"]),
        )
        conn.commit()
    finally:
        conn.close()

    return jsonify({"session_id": session_id, "reply": out})


@app.route("/api/sourcing", methods=["GET"])
def api_sourcing():
    """选品评分结果（带缓存）"""
    cache_path = ROOT / "data" / "sourcing_cache.json"
    use_cache = request.args.get("refresh", "0") != "1"
    if cache_path.exists() and use_cache:
        mtime = cache_path.stat().st_mtime
        age_seconds = (datetime.now().timestamp() - mtime)
        if age_seconds < 60 * 60 * 6:  # 6 小时缓存
            with open(cache_path, "r", encoding="utf-8") as f:
                return jsonify(json.load(f))

    res = score_all()
    out = {
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "weights": {"market": 0.25, "growth": 0.20, "fit": 0.20, "margin": 0.15, "barrier": 0.10, "sea": 0.10},
        "scores": res,
    }

    # 写入数据库 + 缓存
    conn = sqlite3.connect(DB_FILE)
    cur = conn.cursor()
    for r in res:
        cur.execute(
            """INSERT INTO sourcing_scores
               (sku, score_total, score_market, score_growth, score_fit,
                score_margin, score_barrier, score_sea, tier, recommend_actions)
               VALUES (?,?,?,?,?,?,?,?,?,?)""",
            (
                r["sku"], r["total_score"],
                r["dimensions"]["market"]["score"],
                r["dimensions"]["growth"]["score"],
                r["dimensions"]["fit"]["score"],
                r["dimensions"]["margin"]["score"],
                r["dimensions"]["barrier"]["score"],
                r["dimensions"]["sea"]["score"],
                r["tier"],
                json.dumps(r["recommend_actions"], ensure_ascii=False),
            ),
        )
    conn.commit()
    conn.close()

    with open(cache_path, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=2)
    return jsonify(out)


@app.route("/api/data-sources", methods=["GET"])
def api_data_sources():
    """返回所有免费数据源聚合结果"""
    agg = DataAggregator()
    return jsonify(agg.fetch_all())


@app.route("/api/dashboard", methods=["GET"])
def api_dashboard():
    """管理后台用的统计接口"""
    conn = sqlite3.connect(DB_FILE)
    cur = conn.cursor()
    try:
        total_customers = cur.execute("SELECT COUNT(*) FROM customers").fetchone()[0]
        total_inquiries = cur.execute("SELECT COUNT(*) FROM inquiries").fetchone()[0]
        new_inquiries = cur.execute("SELECT COUNT(*) FROM inquiries WHERE status='new'").fetchone()[0]
        total_chats = cur.execute("SELECT COUNT(*) FROM chat_logs").fetchone()[0]
        recent_inq = cur.execute(
            """SELECT i.id, c.name, c.country, i.sku, i.quantity_rolls, i.status, i.created_at
               FROM inquiries i LEFT JOIN customers c ON i.customer_id=c.id
               ORDER BY i.id DESC LIMIT 10"""
        ).fetchall()
        recent_inq = [
            {
                "id": r[0], "customer": r[1], "country": r[2], "sku": r[3],
                "qty": r[4], "status": r[5], "created_at": r[6],
            }
            for r in recent_inq
        ]
        countries = cur.execute(
            """SELECT country, COUNT(*) FROM inquiries i
               JOIN customers c ON i.customer_id=c.id
               GROUP BY country ORDER BY 2 DESC"""
        ).fetchall()
        return jsonify({
            "stats": {
                "total_customers": total_customers,
                "total_inquiries": total_inquiries,
                "new_inquiries": new_inquiries,
                "total_chats": total_chats,
            },
            "recent_inquiries": recent_inq,
            "country_distribution": [{"country": c or "未知", "count": n} for c, n in countries],
        })
    finally:
        conn.close()


@app.route("/api/health")
def health():
    return jsonify({"status": "ok", "ts": datetime.now().isoformat()})


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
    print(f"   📦 数据库:       {DB_FILE}\n")
    app.run(host="0.0.0.0", port=port, debug=False)
