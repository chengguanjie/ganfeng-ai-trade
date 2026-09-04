"""
赣丰玻纤 · 数据库初始化
=========================
在 PostgreSQL（设置了 DATABASE_URL）或 SQLite（本地）上建表并导入基础数据。

7 张表：
1. products          12 SKU 主数据
2. customers         询盘客户
3. inquiries         询盘记录
4. sourcing_scores   选品评分历史
5. chat_logs         客服对话日志
6. automation_log    自动化触发日志
7. data_cache        外部数据源缓存
"""
from __future__ import annotations

import json
import logging
import os
import sys

THIS_DIR = os.path.dirname(os.path.abspath(__file__))
ROOT_DIR = os.path.dirname(THIS_DIR)
sys.path.insert(0, THIS_DIR)

from db import connect, q, init_schema, backend_name, IS_PG, SQLITE_FILE  # type: ignore

logger = logging.getLogger("init_db")

# 兼容旧引用
DB_FILE = SQLITE_FILE

SKU_FILE = os.path.join(ROOT_DIR, "data", "sku.json")


def _upsert_products() -> int:
    with open(SKU_FILE, "r", encoding="utf-8") as f:
        products = json.load(f)["products"]

    cols = """(sku, name_zh, name_en, gram, mesh_size, width, length_per_roll,
               application, scenarios, unit_cost_cny, target_price_usd_per_sqm,
               moq_rolls, lead_time_days)"""
    placeholders = "(?,?,?,?,?,?,?,?,?,?,?,?,?)"

    if IS_PG:
        sql = f"""INSERT INTO products {cols} VALUES {placeholders}
                  ON CONFLICT (sku) DO UPDATE SET
                    name_zh = EXCLUDED.name_zh,
                    name_en = EXCLUDED.name_en,
                    gram = EXCLUDED.gram,
                    mesh_size = EXCLUDED.mesh_size,
                    width = EXCLUDED.width,
                    length_per_roll = EXCLUDED.length_per_roll,
                    application = EXCLUDED.application,
                    scenarios = EXCLUDED.scenarios,
                    unit_cost_cny = EXCLUDED.unit_cost_cny,
                    target_price_usd_per_sqm = EXCLUDED.target_price_usd_per_sqm,
                    moq_rolls = EXCLUDED.moq_rolls,
                    lead_time_days = EXCLUDED.lead_time_days"""
    else:
        sql = f"INSERT OR REPLACE INTO products {cols} VALUES {placeholders}"

    with connect() as conn:
        cur = conn.cursor()
        for p in products:
            gram = p.get("gram")
            cur.execute(
                q(sql),
                (
                    p["sku"],
                    p["name_zh"],
                    p["name_en"],
                    gram if isinstance(gram, (int, float)) else None,
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
    return len(products)


SAMPLE_CUSTOMERS = [
    ("Ali Mahmoud", "Gulf Construction LLC", "Saudi Arabia", "ali@gulfco.sa", None, "buy_sample"),
    ("Sarah Johnson", "Pacific Insulation Inc.", "USA", "s.johnson@pacificins.com", "+1-415-555-0167", "rfq"),
    ("Michael Schmidt", "Deutsche Bauchemie", "Germany", "m.schmidt@db-bauchemie.de", "+49-30-12345", "quote"),
]

SAMPLE_INQUIRIES = [
    ("GF-AR-145-44", 800, 40000, "Need quotation for 145g EIFS mesh, FOB Ningbo", "website"),
    ("GF-WP-160-55", 1500, 75000, "Waterproofing mesh 160g for commercial project", "email"),
    ("GF-SA-75-33", 5000, None, "Joint tape urgent order, want CI sample", "alibaba"),
]


def _seed_samples() -> None:
    """仅当客户表为空时写入演示样本。"""
    with connect() as conn:
        cur = conn.cursor()
        cur.execute("SELECT COUNT(*) FROM customers")
        if cur.fetchone()[0] > 0:
            return

        customer_ids: list[int] = []
        for c in SAMPLE_CUSTOMERS:
            if IS_PG:
                cur.execute(
                    q("""INSERT INTO customers (name, company, country, email, phone, intent)
                         VALUES (?,?,?,?,?,?) RETURNING id"""),
                    c,
                )
                customer_ids.append(int(cur.fetchone()[0]))
            else:
                cur.execute(
                    """INSERT INTO customers (name, company, country, email, phone, intent)
                       VALUES (?,?,?,?,?,?)""",
                    c,
                )
                customer_ids.append(int(cur.lastrowid))

        for cid, inq in zip(customer_ids, SAMPLE_INQUIRIES):
            cur.execute(
                q("""INSERT INTO inquiries (customer_id, sku, quantity_rolls, quantity_sqm, message, source)
                     VALUES (?,?,?,?,?,?)"""),
                (cid, *inq),
            )
    logger.info("seeded %d sample customers + inquiries", len(SAMPLE_CUSTOMERS))


def bootstrap(seed: bool = True) -> None:
    """建表 + 导入 SKU + （可选）演示样本。应用启动时调用。"""
    init_schema()
    n = _upsert_products()
    logger.info("%d SKU upserted", n)
    if seed:
        _seed_samples()
        # V8：SEO/GEO 与客服分析的演示数据（幂等，已有数据则跳过）
        try:
            from seo_engine import ensure_seed as _seo_seed  # type: ignore
            _seo_seed()
        except Exception as e:
            logger.warning("seo seed failed: %s", e)
        try:
            from chat_analytics import ensure_seed as _chat_seed  # type: ignore
            _chat_seed()
        except Exception as e:
            logger.warning("chat seed failed: %s", e)


# ── 兼容旧接口 ─────────────────────────────────────
def init_db(db_path: str | None = None):
    bootstrap(seed=False)
    return None


def insert_sample_data(conn=None) -> None:
    _seed_samples()


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    print(f"backend = {backend_name()}")
    bootstrap(seed=True)
    with connect() as c:
        cur = c.cursor()
        for t in ("products", "customers", "inquiries", "sourcing_scores", "chat_logs", "automation_log", "data_cache"):
            cur.execute(f"SELECT COUNT(*) FROM {t}")
            print(f"  {t:18s} {cur.fetchone()[0]:>6d} rows")
    print("\n✅ 数据库就绪")
