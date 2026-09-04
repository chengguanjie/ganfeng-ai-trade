"""
赣丰玻纤 · 智能客服分析引擎（V8 数据飞轮 - 客服引擎）
=====================================================

职责：
  1. 会话级统计（会话数 / 消息数 / LLM 使用率 / 语言分布）
  2. 意图分布 + 高意向识别（moq_quote / sample / recommend 等）
  3. 转化漏斗：会话 → 高意向会话 → 沉淀询盘（source='chat'）
  4. 高频问题 Top N（客服数据反哺 SEO 内容选题 —— 飞轮第 ④ 环节）
  5. 会话详情查看（管理员可读完整对话记录）

表：chat_logs（已有） + inquiries（source='chat'）
"""
from __future__ import annotations

import logging
import re
from datetime import datetime, timedelta
from typing import Any

from db import connect, q, insert_returning_id, IS_PG  # type: ignore

logger = logging.getLogger("chat-analytics")

# 高购买意向意图（V8 方案 ⑥ 飞轮分层标准）
HIGH_INTENT = {"moq_quote", "sample", "recommend", "oem", "supply"}

INTENT_LABELS = {
    "moq_quote": "询价/MOQ", "sample": "样品", "logistics": "物流",
    "payment": "付款", "cert": "认证", "spec_consult": "规格咨询",
    "recommend": "求推荐", "oem": "OEM 定制", "supply": "产能/交期",
    "aftersale": "售后", "company": "了解公司", "product_intro": "产品介绍",
    "channel": "渠道代理", "general": "通用",
}

# -----------------------------------------------------------
# 演示种子：8 个会话（含 1 个转化 → 询盘）
# -----------------------------------------------------------
_DEMO_SESSIONS: list[dict[str, Any]] = [
    {
        "session_id": "demo-001", "days_ago": 13, "lang": "en",
        "msgs": [
            ("user", "What's your MOQ for 145g mesh?", "moq_quote"),
            ("bot", "Standard SKU MOQ is 200 rolls (~one 20GP)... New customers get a 100-roll trial + 5 free sample rolls.", "moq_quote"),
            ("user", "Can I get samples first?", "sample"),
            ("bot", "Sample policy: 5 free rolls per SKU (DHL freight collect), 3-5 days...", "sample"),
            ("user", "Great, I'll submit an inquiry now.", "moq_quote"),
        ],
        "converted": True, "country": "Saudi Arabia",
    },
    {
        "session_id": "demo-002", "days_ago": 11, "lang": "en",
        "msgs": [
            ("user", "delivery time to Saudi Arabia?", "logistics"),
            ("bot", "Sea transit to Middle East: 18-22 days. Incoterms FOB/CIF...", "logistics"),
            ("user", "And your payment terms?", "payment"),
            ("bot", "New customers: 30% T/T deposit + 70% against B/L copy...", "payment"),
        ],
        "converted": False, "country": "Saudi Arabia",
    },
    {
        "session_id": "demo-003", "days_ago": 9, "lang": "zh",
        "msgs": [
            ("user", "外墙保温用多少克的网格布？", "recommend"),
            ("bot", "EWI 系统推荐 145-160g 抗碱网格布...", "recommend"),
            ("user", "145g 抗拉强度多少？", "spec_consult"),
            ("bot", "145g 4x4mm 经向 ≥1400 N/50mm...", "spec_consult"),
        ],
        "converted": False, "country": "China",
    },
    {
        "session_id": "demo-004", "days_ago": 7, "lang": "en",
        "msgs": [
            ("user", "Do you have ISO certification?", "cert"),
            ("bot", "Certifications: ISO 9001:2015 + ISO 14001:2015 + CE + RoHS...", "cert"),
            ("user", "Can you do OEM packaging?", "oem"),
            ("bot", "OEM services: Custom LOGO, brand packaging... MOQ 1000 rolls.", "oem"),
            ("user", "Please quote 5000 rolls OEM.", "oem"),
        ],
        "converted": False, "country": "UAE",
    },
    {
        "session_id": "demo-005", "days_ago": 5, "lang": "en",
        "msgs": [
            ("user", "How about your factory capacity?", "supply"),
            ("bot", "Capacity: 12 weaving lines + 5 coating lines, 8000 tons/year...", "supply"),
            ("user", "send me a quote for 1000 rolls 160g", "moq_quote"),
        ],
        "converted": True, "country": "Vietnam",
    },
    {
        "session_id": "demo-006", "days_ago": 4, "lang": "en",
        "msgs": [
            ("user", "what is fiberglass mesh used for?", "product_intro"),
            ("bot", "Fiberglass mesh is used to reinforce EWI systems, waterproofing membranes...", "product_intro"),
        ],
        "converted": False, "country": "India",
    },
    {
        "session_id": "demo-007", "days_ago": 2, "lang": "zh",
        "msgs": [
            ("user", "你们可以做区域独家代理吗？", "channel"),
            ("bot", "经销商合作：新区域独家代理提供样品支持、技术培训...", "channel"),
        ],
        "converted": False, "country": "China",
    },
    {
        "session_id": "demo-008", "days_ago": 1, "lang": "en",
        "msgs": [
            ("user", "sample price for 90g mesh?", "sample"),
            ("bot", "5 free sample rolls per SKU, DHL freight collect...", "sample"),
            ("user", "what's the tensile strength of 90g?", "spec_consult"),
            ("bot", "90g 4x4mm: warp ≥900 N/50mm, weft ≥850 N/50mm...", "spec_consult"),
            ("user", "ok send me samples, inquiry submitted", "sample"),
        ],
        "converted": True, "country": "Turkey",
    },
]


def ensure_seed() -> None:
    """写入演示会话（幂等：按 demo- 会话 ID 判断，已有真实数据也不冲突）。"""
    with connect() as conn:
        cur = conn.cursor()
        cur.execute(q("SELECT COUNT(DISTINCT session_id) FROM chat_logs WHERE session_id LIKE 'demo-%'"))
        if cur.fetchone()[0] >= len(_DEMO_SESSIONS):
            return

        now = datetime.now()
        for s in _DEMO_SESSIONS:
            cur.execute(
                q("SELECT COUNT(*) FROM chat_logs WHERE session_id = ?"), (s["session_id"],)
            )
            if cur.fetchone()[0] > 0:
                continue  # 该演示会话已存在，跳过
            ts = now - timedelta(days=s["days_ago"])
            for i, (role, msg, intent) in enumerate(s["msgs"]):
                cur.execute(
                    q("""INSERT INTO chat_logs (session_id, message, role, intent, created_at)
                         VALUES (?,?,?,?,?)"""),
                    (s["session_id"], msg, role, intent,
                     (ts + timedelta(minutes=i)).strftime("%Y-%m-%d %H:%M:%S")),
                )
            # 转化会话 → 写入一条 source='chat' 的询盘
            if s["converted"]:
                cid = insert_returning_id(
                    cur,
                    q("""INSERT INTO customers (name, company, country, email, intent, layer)
                         VALUES (?,?,?,?,?,?)"""),
                    (f"Chat Visitor {s['session_id'][-3:].upper()}", "—", s.get("country", ""), "", "rfq", "hot"),
                )
                cur.execute(
                    q("""INSERT INTO inquiries (customer_id, sku, message, source, status)
                         VALUES (?,?,?,?,?)"""),
                    (cid, None, "Converted from AI chat session", "chat", "new"),
                )
        logger.info("chat demo sessions seeded: %d", len(_DEMO_SESSIONS))


# -----------------------------------------------------------
# 分析聚合
# -----------------------------------------------------------
def analytics() -> dict[str, Any]:
    """客服全量分析数据（管理后台 Tab 3）。"""
    with connect() as conn:
        cur = conn.cursor()

        # 会话级基础统计
        cur.execute(
            q("""SELECT COUNT(DISTINCT session_id), COUNT(*),
                       SUM(CASE WHEN role='user' THEN 1 ELSE 0 END)
                FROM chat_logs""")
        )
        total_sessions, total_msgs, user_msgs = cur.fetchone() or (0, 0, 0)

        # 意图分布（按用户消息）
        cur.execute(
            q("""SELECT intent, COUNT(*) FROM chat_logs
                 WHERE role='user' GROUP BY intent ORDER BY 2 DESC""")
        )
        intent_dist = [
            {"intent": r[0] or "general",
             "label": INTENT_LABELS.get(r[0], r[0] or "通用"),
             "count": r[1]}
            for r in cur.fetchall()
        ]
        high_intent_msgs = sum(d["count"] for d in intent_dist if d["intent"] in HIGH_INTENT)
        total_user_msgs = user_msgs or 1

        # 高意向会话（出现过一次高意向意图即算）
        cur.execute(
            q("""SELECT session_id, COUNT(*) FROM chat_logs
                 WHERE role='user' AND intent IN ('moq_quote','sample','recommend','oem','supply')
                 GROUP BY session_id""")
        )
        high_sessions = {r[0] for r in cur.fetchall()}
        total_sessions = total_sessions or 0
        high_session_count = len(high_sessions)

        # 转化：source='chat' 的询盘数
        cur.execute(q("SELECT COUNT(*) FROM inquiries WHERE source='chat'"))
        chat_inquiries = cur.fetchone()[0] or 0
        cur.execute(q("SELECT COUNT(*) FROM inquiries"))
        total_inquiries = cur.fetchone()[0] or 0

        # 每日会话趋势（14 天）
        cutoff = (datetime.now() - timedelta(days=13)).strftime("%Y-%m-%d")
        cur.execute(
            q("""SELECT SUBSTR(created_at, 1, 10) AS d, COUNT(DISTINCT session_id)
                 FROM chat_logs WHERE created_at >= ? GROUP BY d ORDER BY d"""),
            (cutoff,),
        )
        daily_sessions = [{"date": r[0], "sessions": r[1]} for r in cur.fetchall()]

        # 会话列表（含首条消息 + 意图 + 是否高意向 + 是否转化）
        cur.execute(
            q("""SELECT session_id,
                        MIN(CASE WHEN role='user' THEN created_at END),
                        COUNT(*) AS msgs
                 FROM chat_logs GROUP BY session_id
                 ORDER BY MIN(created_at) DESC LIMIT 50""")
        )
        sessions = []
        for sid, first_at, nmsgs in cur.fetchall():
            cur.execute(
                q("""SELECT message, intent FROM chat_logs
                     WHERE session_id = ? AND role='user' ORDER BY id LIMIT 1"""),
                (sid,),
            )
            row = cur.fetchone()
            first_msg = row[0] if row else ""
            first_intent = (row[1] if row else "general") or "general"
            cur.execute(
                q("""SELECT DISTINCT intent FROM chat_logs
                     WHERE session_id = ? AND role='user'
                       AND intent IN ('moq_quote','sample','recommend','oem','supply')"""),
                (sid,),
            )
            hi_intents = [r[0] for r in cur.fetchall()]
            sessions.append({
                "session_id": sid,
                "first_message": (first_msg[:60] + "…") if len(first_msg) > 60 else first_msg,
                "intent": first_intent,
                "intent_label": INTENT_LABELS.get(first_intent, first_intent),
                "messages": nmsgs,
                "high_intent": bool(hi_intents),
                "high_intents": hi_intents,
                "started_at": str(first_at)[:16] if first_at else "",
            })

        # 高频问题 Top 10（飞轮反哺 SEO 选题的数据源）
        cur.execute(
            q("""SELECT message, COUNT(*) FROM chat_logs
                 WHERE role='user' GROUP BY message ORDER BY 2 DESC LIMIT 10""")
        )
        top_questions = [
            {"question": r[0], "count": r[1]}
            for r in cur.fetchall() if r[0]
        ]

        # LLM 使用率：无法直接区分，用「非模板回复」近似 — 当前先返回会话覆盖率
        # （后续 llm_client 增加标记后可精确统计）

        conv_sessions = sum(1 for s in sessions if s["high_intent"])
        return {
            "generated_at": datetime.now().isoformat(timespec="seconds"),
            "kpi": {
                "total_sessions": total_sessions,
                "total_messages": total_msgs,
                "user_messages": user_msgs,
                "avg_messages_per_session": round(total_msgs / total_sessions, 1) if total_sessions else 0,
                "high_intent_sessions": conv_sessions,
                "high_intent_rate": round(conv_sessions / total_sessions, 3) if total_sessions else 0,
                "chat_inquiries": chat_inquiries,
                "chat_conversion_rate": round(chat_inquiries / total_sessions, 3) if total_sessions else 0,
                "inquiry_share_from_chat": round(chat_inquiries / total_inquiries, 3) if total_inquiries else 0,
                "high_intent_msg_rate": round(high_intent_msgs / total_user_msgs, 3),
            },
            "intent_distribution": intent_dist,
            "daily_sessions": daily_sessions,
            "funnel": {
                "chat_sessions": total_sessions,
                "high_intent": conv_sessions,
                "inquiries": chat_inquiries,
            },
            "sessions": sessions,
            "top_questions": top_questions,
        }


def session_detail(session_id: str) -> dict[str, Any]:
    """单个会话的完整对话记录。"""
    with connect() as conn:
        cur = conn.cursor()
        cur.execute(
            q("""SELECT role, message, intent, created_at FROM chat_logs
                 WHERE session_id = ? ORDER BY id"""),
            (session_id,),
        )
        messages = [
            {"role": r[0], "message": r[1], "intent": r[2], "time": str(r[3])[:16]}
            for r in cur.fetchall()
        ]
        return {"session_id": session_id, "messages": messages}


if __name__ == "__main__":
    import json as _json
    logging.basicConfig(level=logging.INFO)
    ensure_seed()
    print(_json.dumps(analytics()["kpi"], ensure_ascii=False, indent=2))
