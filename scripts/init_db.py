"""
赣丰玻纤 · SQLite 数据库初始化
=================================
5 张主表（与 V4/V5 飞书多维表格字段一致）：
1. products：12 SKU 主数据
2. customers：询盘客户主数据
3. inquiries：询盘/表单提交记录
4. sourcing_scores：选品评分结果历史
5. chat_logs：客服对话日志

由于本项目独立站是 PC 端演示版本，未接入 lark-base 真实 API，
所有数据先落到本地 SQLite，再由 lark-base 同步层写入飞书（如已开通）。
"""
from __future__ import annotations
import sqlite3
import os
import json
import sys
from datetime import datetime

THIS_DIR = os.path.dirname(os.path.abspath(__file__))
ROOT_DIR = os.path.dirname(THIS_DIR)
DB_FILE = os.path.join(ROOT_DIR, "data", "trade.db")

SCHEMA = """
CREATE TABLE IF NOT EXISTS products (
    sku TEXT PRIMARY KEY,
    name_zh TEXT NOT NULL,
    name_en TEXT,
    gram INTEGER,
    mesh_size TEXT,
    width TEXT,
    length_per_roll TEXT,
    application TEXT,
    scenarios TEXT,
    unit_cost_cny REAL,
    target_price_usd_per_sqm REAL,
    moq_rolls INTEGER,
    lead_time_days INTEGER,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS customers (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    company TEXT,
    country TEXT,
    email TEXT,
    phone TEXT,
    intent TEXT,
    layer TEXT DEFAULT 'cold',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS inquiries (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    customer_id INTEGER,
    sku TEXT,
    quantity_rolls INTEGER,
    quantity_sqm REAL,
    message TEXT,
    source TEXT DEFAULT 'website',
    status TEXT DEFAULT 'new',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (customer_id) REFERENCES customers(id)
);

CREATE TABLE IF NOT EXISTS sourcing_scores (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    sku TEXT NOT NULL,
    score_total REAL,
    score_market REAL,
    score_growth REAL,
    score_fit REAL,
    score_margin REAL,
    score_barrier REAL,
    score_sea REAL,
    tier TEXT,
    recommend_actions TEXT,
    fetched_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS chat_logs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id TEXT,
    customer_id INTEGER,
    message TEXT,
    role TEXT,
    intent TEXT,
    matched_faq_id INTEGER,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS automation_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    trigger_type TEXT,
    trigger_payload TEXT,
    action_taken TEXT,
    status TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_inquiries_status ON inquiries(status);
CREATE INDEX IF NOT EXISTS idx_chat_log_session ON chat_logs(session_id);
CREATE INDEX IF NOT EXISTS idx_sourcing_total ON sourcing_scores(sku, score_total);
"""


def init_db(db_path: str = DB_FILE) -> sqlite3.Connection:
    os.makedirs(os.path.dirname(db_path), exist_ok=True)
    conn = sqlite3.connect(db_path)
    conn.executescript(SCHEMA)
    conn.commit()

    # 初始化 SKU 主数据（如果为空）
    cur = conn.cursor()
    cur.execute("SELECT COUNT(*) FROM products")
    if cur.fetchone()[0] == 0:
        sku_file = os.path.join(ROOT_DIR, "data", "sku.json")
        with open(sku_file, "r", encoding="utf-8") as f:
            products = json.load(f)["products"]
        for p in products:
            cur.execute(
                """INSERT OR REPLACE INTO products
                   (sku, name_zh, name_en, gram, mesh_size, width, length_per_roll,
                    application, scenarios, unit_cost_cny, target_price_usd_per_sqm,
                    moq_rolls, lead_time_days)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (
                    p["sku"],
                    p["name_zh"],
                    p["name_en"],
                    p.get("gram", None) if isinstance(p.get("gram"), (int, float)) else None,
                    p.get("mesh_size", ""),
                    p.get("width", ""),
                    p.get("length_per_roll", ""),
                    ", ".join(p.get("applications", [])),
                    ", ".join(p.get("scenarios", [])),
                    p.get("unit_cost_cny", 0),
                    p.get("target_price_usd_per_sqm", 0),
                    p.get("moq_rolls", 200),
                    p.get("lead_time_days", 20),
                ),
            )
        conn.commit()
        print(f"[init] {len(products)} SKU 已导入")

    return conn


def insert_sample_data(conn: sqlite3.Connection) -> None:
    """演示用样本数据，方便管理后台展示"""
    cur = conn.cursor()
    # 客户
    cur.execute("SELECT COUNT(*) FROM customers")
    if cur.fetchone()[0] == 0:
        sample_customers = [
            ("Ali Mahmoud", "Gulf Construction LLC", "Saudi Arabia", "ali@gulfco.sa", None, "buy_sample"),
            ("Sarah Johnson", "Pacific Insulation Inc.", "USA", "s.johnson@pacificins.com", "+1-415-555-0167", "rfq"),
            ("Michael Schmidt", "Deutsche Bauchemie", "Germany", "m.schmidt@db-bauchemie.de", "+49-30-12345", "quote"),
        ]
        for c in sample_customers:
            cur.execute(
                "INSERT INTO customers (name, company, country, email, phone, intent) VALUES (?,?,?,?,?,?)",
                c,
            )
        conn.commit()
        print("[init] 3 客户样本已写入")

    # 询盘
    cur.execute("SELECT COUNT(*) FROM inquiries")
    if cur.fetchone()[0] == 0:
        cur.execute("SELECT id FROM customers ORDER BY id ASC LIMIT 3")
        ids = [r[0] for r in cur.fetchall()]
        sample_inq = [
            (ids[0], "GF-AR-145-44", 800, 40000, "Need quotation for 145g EIFS mesh, FOB Ningbo", "website"),
            (ids[1], "GF-WP-160-55", 1500, 75000, "Waterproofing mesh 160g for commercial project", "email"),
            (ids[2], "GF-SA-75-33", 5000, None, "Joint tape urgent order, want CI sample", "alibaba"),
        ]
        for i in sample_inq:
            cur.execute(
                "INSERT INTO inquiries (customer_id, sku, quantity_rolls, quantity_sqm, message, source) VALUES (?,?,?,?,?,?)",
                i,
            )
        conn.commit()
        print("[init] 3 询盘样本已写入")


if __name__ == "__main__":
    conn = init_db()
    insert_sample_data(conn)
    print(f"\n✅ 数据库就绪: {DB_FILE}")
