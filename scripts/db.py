"""
赣丰玻纤 · 数据库抽象层（PostgreSQL 优先 / SQLite 降级）
=========================================================

选择规则：
  设置了 DATABASE_URL（postgres://... 或 postgresql://...）→ 用 PostgreSQL
  否则                                                    → 用本地 SQLite

对外只暴露一套 API，业务代码不需要区分后端：

    from db import connect, q, insert_returning_id, IS_PG

    with connect() as conn:
        cur = conn.cursor()
        cur.execute(q("SELECT * FROM inquiries WHERE status = ?"), ("new",))

占位符统一写 `?`，由 q() 在 PostgreSQL 下翻译为 `%s`。
"""
from __future__ import annotations

import os
import json
import logging
import sqlite3
from contextlib import contextmanager
from typing import Any, Iterator

logger = logging.getLogger("db")

THIS_DIR = os.path.dirname(os.path.abspath(__file__))
ROOT_DIR = os.path.dirname(THIS_DIR)
SQLITE_FILE = os.path.join(ROOT_DIR, "data", "trade.db")

DATABASE_URL = (os.environ.get("DATABASE_URL") or "").strip()
IS_PG = DATABASE_URL.startswith(("postgres://", "postgresql://"))

# 兼容 DB_FILE 旧引用
DB_FILE = SQLITE_FILE


def backend_name() -> str:
    return "postgresql" if IS_PG else "sqlite"


def q(sql: str) -> str:
    """把 `?` 占位符翻译成当前后端的风格。"""
    if not IS_PG:
        return sql
    out: list[str] = []
    in_single = False
    in_double = False
    for ch in sql:
        if ch == "'" and not in_double:
            in_single = not in_single
        elif ch == '"' and not in_single:
            in_double = not in_double
        if ch == "?" and not in_single and not in_double:
            out.append("%s")
        else:
            out.append(ch)
    return "".join(out)


@contextmanager
def connect() -> Iterator[Any]:
    """获取数据库连接（上下文管理，自动 commit / rollback / close）。"""
    if IS_PG:
        import psycopg

        conn = psycopg.connect(DATABASE_URL, connect_timeout=15)
    else:
        os.makedirs(os.path.dirname(SQLITE_FILE), exist_ok=True)
        conn = sqlite3.connect(SQLITE_FILE, timeout=15)
    try:
        yield conn
        conn.commit()
    except Exception:
        try:
            conn.rollback()
        except Exception:
            pass
        raise
    finally:
        conn.close()


def insert_returning_id(cur: Any, sql: str, params: tuple) -> int:
    """执行 INSERT 并返回自增主键，屏蔽 lastrowid / RETURNING 差异。"""
    if IS_PG:
        cur.execute(q(sql.rstrip().rstrip(";") + " RETURNING id"), params)
        return int(cur.fetchone()[0])
    cur.execute(sql, params)
    return int(cur.lastrowid)


# ============================================================
# Schema
# ============================================================
_SERIAL = "SERIAL PRIMARY KEY" if IS_PG else "INTEGER PRIMARY KEY AUTOINCREMENT"
_TS = "TIMESTAMP DEFAULT CURRENT_TIMESTAMP"
_JSONCOL = "TEXT"

SCHEMA_STATEMENTS = [
    f"""CREATE TABLE IF NOT EXISTS products (
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
        created_at {_TS}
    )""",
    f"""CREATE TABLE IF NOT EXISTS customers (
        id {_SERIAL},
        name TEXT NOT NULL,
        company TEXT,
        country TEXT,
        email TEXT,
        phone TEXT,
        intent TEXT,
        layer TEXT DEFAULT 'cold',
        feishu_record_id TEXT,
        created_at {_TS}
    )""",
    f"""CREATE TABLE IF NOT EXISTS inquiries (
        id {_SERIAL},
        customer_id INTEGER,
        sku TEXT,
        quantity_rolls INTEGER,
        quantity_sqm REAL,
        message TEXT,
        source TEXT DEFAULT 'website',
        status TEXT DEFAULT 'new',
        ai_intent TEXT,
        ai_layer TEXT,
        feishu_record_id TEXT,
        created_at {_TS}
    )""",
    f"""CREATE TABLE IF NOT EXISTS sourcing_scores (
        id {_SERIAL},
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
        ai_reason TEXT,
        target_market TEXT,
        fetched_at {_TS}
    )""",
    f"""CREATE TABLE IF NOT EXISTS chat_logs (
        id {_SERIAL},
        session_id TEXT,
        customer_id INTEGER,
        message TEXT,
        role TEXT,
        intent TEXT,
        matched_faq_id INTEGER,
        created_at {_TS}
    )""",
    f"""CREATE TABLE IF NOT EXISTS automation_log (
        id {_SERIAL},
        trigger_type TEXT,
        trigger_payload TEXT,
        action_taken TEXT,
        status TEXT,
        created_at {_TS}
    )""",
    f"""CREATE TABLE IF NOT EXISTS data_cache (
        source TEXT PRIMARY KEY,
        payload {_JSONCOL},
        status TEXT,
        fetched_at {_TS}
    )""",
    # ── V8：SEO/GEO 推广引擎 ──────────────────────
    f"""CREATE TABLE IF NOT EXISTS seo_keywords (
        id {_SERIAL},
        keyword TEXT NOT NULL,
        layer TEXT,
        target_path TEXT,
        volume_month INTEGER,
        competition TEXT,
        rank INTEGER,
        status TEXT DEFAULT 'tracking',
        created_at {_TS}
    )""",
    f"""CREATE TABLE IF NOT EXISTS seo_pages (
        id {_SERIAL},
        path TEXT UNIQUE NOT NULL,
        title TEXT,
        meta_desc TEXT,
        impressions_7d INTEGER DEFAULT 0,
        clicks_7d INTEGER DEFAULT 0,
        avg_position REAL,
        status TEXT DEFAULT 'active',
        last_optimized_at TIMESTAMP,
        created_at {_TS}
    )""",
    f"""CREATE TABLE IF NOT EXISTS seo_daily (
        id {_SERIAL},
        stat_date TEXT NOT NULL,
        path TEXT NOT NULL,
        impressions INTEGER,
        clicks INTEGER,
        position REAL,
        created_at {_TS}
    )""",
    f"""CREATE TABLE IF NOT EXISTS geo_checks (
        id {_SERIAL},
        check_date TEXT NOT NULL,
        question TEXT NOT NULL,
        engine TEXT NOT NULL,
        mentioned INTEGER DEFAULT 0,
        created_at {_TS}
    )""",
    f"""CREATE TABLE IF NOT EXISTS seo_optimizations (
        id {_SERIAL},
        path TEXT NOT NULL,
        field TEXT,
        old_value TEXT,
        new_value TEXT,
        reason TEXT,
        applied_at {_TS}
    )""",
    f"""CREATE TABLE IF NOT EXISTS publish_log (
        id {_SERIAL},
        skus {_JSONCOL},
        trigger TEXT,
        detail {_JSONCOL},
        created_at {_TS}
    )""",
    "CREATE INDEX IF NOT EXISTS idx_inquiries_status ON inquiries(status)",
    "CREATE INDEX IF NOT EXISTS idx_chat_log_session ON chat_logs(session_id)",
    "CREATE INDEX IF NOT EXISTS idx_sourcing_total ON sourcing_scores(sku, score_total)",
    "CREATE INDEX IF NOT EXISTS idx_seo_daily_date ON seo_daily(stat_date)",
    "CREATE INDEX IF NOT EXISTS idx_geo_checks_date ON geo_checks(check_date)",
]

# 轻量列迁移（已存在的库升级用；新库由 CREATE 语句天然覆盖）
_COLUMN_MIGRATIONS = [
    ("products", "featured", "INTEGER DEFAULT 0"),
    ("products", "featured_rank", "INTEGER"),
    ("customers", "layer", "TEXT DEFAULT 'cold'"),
    ("inquiries", "ai_intent", "TEXT"),
    ("inquiries", "ai_layer", "TEXT"),
]


def init_schema() -> None:
    """建表（幂等）。"""
    with connect() as conn:
        cur = conn.cursor()
        for stmt in SCHEMA_STATEMENTS:
            cur.execute(stmt)
        # 轻量列迁移（幂等：已存在则忽略报错）
        for table, column, coltype in _COLUMN_MIGRATIONS:
            try:
                cur.execute(f"ALTER TABLE {table} ADD COLUMN {column} {coltype}")
            except Exception:
                pass  # 列已存在
    logger.info("schema ready on %s", backend_name())


# ============================================================
# 数据源缓存
# ============================================================
def cache_get(source: str, ttl_seconds: int) -> dict[str, Any] | None:
    """读取未过期的数据源缓存。"""
    sql = "SELECT payload, fetched_at FROM data_cache WHERE source = ?"
    try:
        with connect() as conn:
            cur = conn.cursor()
            cur.execute(q(sql), (source,))
            row = cur.fetchone()
    except Exception as e:
        logger.warning("cache_get failed for %s: %s", source, e)
        return None
    if not row:
        return None

    payload_raw, fetched_at = row[0], row[1]
    from datetime import datetime, timezone

    if isinstance(fetched_at, str):
        try:
            fetched = datetime.fromisoformat(fetched_at.replace("Z", "+00:00"))
        except ValueError:
            return None
    else:
        fetched = fetched_at
    if fetched.tzinfo is None:
        fetched = fetched.replace(tzinfo=timezone.utc)
    age = (datetime.now(timezone.utc) - fetched).total_seconds()
    if age > ttl_seconds:
        return None
    try:
        return json.loads(payload_raw)
    except Exception:
        return None


def cache_put(source: str, payload: dict[str, Any], status: str = "ok") -> None:
    """写入数据源缓存（upsert）。"""
    blob = json.dumps(payload, ensure_ascii=False)
    try:
        with connect() as conn:
            cur = conn.cursor()
            if IS_PG:
                cur.execute(
                    q(
                        """INSERT INTO data_cache (source, payload, status, fetched_at)
                           VALUES (?, ?, ?, CURRENT_TIMESTAMP)
                           ON CONFLICT (source) DO UPDATE
                             SET payload = EXCLUDED.payload,
                                 status = EXCLUDED.status,
                                 fetched_at = CURRENT_TIMESTAMP"""
                    ),
                    (source, blob, status),
                )
            else:
                cur.execute(
                    """INSERT INTO data_cache (source, payload, status, fetched_at)
                       VALUES (?, ?, ?, CURRENT_TIMESTAMP)
                       ON CONFLICT(source) DO UPDATE
                         SET payload = excluded.payload,
                             status = excluded.status,
                             fetched_at = CURRENT_TIMESTAMP""",
                    (source, blob, status),
                )
    except Exception as e:
        logger.warning("cache_put failed for %s: %s", source, e)


def cache_status() -> list[dict[str, Any]]:
    """所有数据源的缓存状态（供后台展示）。"""
    try:
        with connect() as conn:
            cur = conn.cursor()
            cur.execute("SELECT source, status, fetched_at FROM data_cache ORDER BY source")
            rows = cur.fetchall()
    except Exception:
        return []
    return [
        {"source": r[0], "status": r[1], "fetched_at": str(r[2])[:19]}
        for r in rows
    ]


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    print(f"backend  = {backend_name()}")
    print(f"target   = {'DATABASE_URL' if IS_PG else SQLITE_FILE}")
    init_schema()
    with connect() as c:
        cur = c.cursor()
        for t in ("products", "customers", "inquiries", "sourcing_scores", "chat_logs", "data_cache"):
            cur.execute(f"SELECT COUNT(*) FROM {t}")
            print(f"  {t:18s} {cur.fetchone()[0]:>6d} rows")
