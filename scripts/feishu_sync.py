"""
赣丰玻纤 · 飞书同步与自动化
============================

对应 V5 方案第 ⑤⑥ 章：

  ⑤ 知识库：把 FAQ 灌入多维表格 knowledge_base 表
  ⑥ 自动化：
      new_inquiry     → 群卡片通知 + 写入 inquiries 表 + 回写 record_id
      sourcing_ready  → 选品 Top5 推送群 + 写入 sourcing_scores 表
      full_sync       → 产品/客户/询盘/选品/知识库 全量同步

未配置飞书（缺 LARK_APP_ID/SECRET）或 LARK_DRY_RUN=true 时，
所有操作只打印不发请求，业务链路照常跑通。
"""
from __future__ import annotations

import json
import logging
import os
import sys
from datetime import datetime
from typing import Any

THIS_DIR = os.path.dirname(os.path.abspath(__file__))
ROOT_DIR = os.path.dirname(THIS_DIR)
sys.path.insert(0, THIS_DIR)

from db import connect, q, IS_PG  # type: ignore
import feishu_client  # type: ignore
from feishu_client import FeishuClient, FeishuError  # type: ignore

logger = logging.getLogger("feishu_sync")

FAQ_FILE = os.path.join(ROOT_DIR, "data", "faqs.json")
SKU_FILE = os.path.join(ROOT_DIR, "data", "sku.json")


class FeishuSync:
    """飞书同步器。构造时不发任何请求，按需取 token。"""

    def __init__(self, db_path: str | None = None, dry_run: bool | None = None,
                 client: FeishuClient | None = None):
        # db_path 保留仅为向后兼容旧调用，实际后端由 DATABASE_URL 决定
        self.client = client or feishu_client.get_client()
        if dry_run is not None:
            self.client.dry_run = dry_run

    @property
    def enabled(self) -> bool:
        return feishu_client.is_configured()

    # ========================================================
    # 自动化触发
    # ========================================================
    def trigger_automation(self, event: str, payload: dict[str, Any]) -> dict[str, Any]:
        handlers = {
            "new_inquiry": self._on_new_inquiry,
            "sourcing_ready": self._on_sourcing_ready,
        }
        handler = handlers.get(event)
        if not handler:
            return {"action": event, "status": "no-handler"}

        if not self.enabled:
            logger.info("[飞书未配置] %s: %s", event, json.dumps(payload, ensure_ascii=False)[:200])
            return {"action": f"{event}-skipped", "status": "not-configured"}
        try:
            return handler(payload)
        except FeishuError as e:
            logger.warning("%s 处理失败: %s", event, e)
            return {"action": event, "status": f"error: {e}"}

    def _on_new_inquiry(self, p: dict[str, Any]) -> dict[str, Any]:
        """新询盘：写多维表格 + 群卡片通知 + 回写 record_id。"""
        now = datetime.now().strftime("%Y-%m-%d %H:%M")
        record_id = None
        table_status = "skipped"

        if self.client.base_token:
            res = self.client.create_record("inquiries", {
                "询盘编号": f"INQ-{p.get('inquiry_id')}",
                "客户": p.get("customer"),
                "国家": p.get("country"),
                "目标SKU": p.get("sku"),
                "需求卷数": _num(p.get("qty")),
                "需求面积": _num(p.get("quantity_sqm")),
                "客户留言": p.get("message"),
                "来源": p.get("source"),
                "状态": "新询盘",
                "AI识别意图": p.get("intent"),
                "创建时间": now,
            })
            record_id = res.get("record_id")
            table_status = res.get("status", "ok")
            if record_id and p.get("inquiry_id"):
                self._save_record_id("inquiries", int(p["inquiry_id"]), record_id)

        qty = p.get("qty")
        lines = [
            f"**客户**：{p.get('customer') or '-'}（{p.get('company') or '未填公司'}）",
            f"**国家**：{p.get('country') or '-'}",
            f"**产品**：{p.get('sku') or '未指定'}",
            f"**数量**：{qty if qty else '未填'} 卷",
            f"**邮箱**：{p.get('email') or '-'}",
            f"**留言**：{(p.get('message') or '无')[:120]}",
            f"**来源**：{p.get('source') or 'website'}　**时间**：{now}",
            "",
            "请在 **24 小时内** 完成首次回复。",
        ]
        msg = self.client.send_card(
            f"🔔 新询盘 INQ-{p.get('inquiry_id')}",
            lines,
            color="orange",
        )
        return {
            "action": "feishu-inquiry-sync",
            "status": f"table={table_status}, notify={msg.get('status')}",
            "record_id": record_id,
        }

    def _on_sourcing_ready(self, p: dict[str, Any]) -> dict[str, Any]:
        """选品结果就绪：Top5 推群。"""
        scores = p.get("scores", [])[:5]
        if not scores:
            return {"action": "feishu-sourcing", "status": "empty"}
        lines = [f"**数据源状态**：{p.get('data_status', 'n/a')}", ""]
        for i, s in enumerate(scores, 1):
            lines.append(
                f"**{i}. {s.get('sku')}** {s.get('name_zh', '')}　"
                f"总分 **{s.get('total_score')}**（{s.get('tier')}）"
            )
            if s.get("ai_reason"):
                lines.append(f"　　{s['ai_reason']}")
            if s.get("target_market"):
                lines.append(f"　　🎯 {s['target_market']}")
        msg = self.client.send_card("📊 本期选品 Top 5", lines, color="blue")
        return {"action": "feishu-sourcing-notify", "status": msg.get("status")}

    def _save_record_id(self, table: str, row_id: int, record_id: str) -> None:
        try:
            with connect() as conn:
                conn.cursor().execute(
                    q(f"UPDATE {table} SET feishu_record_id = ? WHERE id = ?"),
                    (record_id, row_id),
                )
        except Exception as e:
            logger.warning("回写 feishu_record_id 失败: %s", e)

    # ========================================================
    # 全量同步
    # ========================================================
    def sync_all(self) -> dict[str, Any]:
        if not self.enabled:
            return {"status": "not-configured",
                    "hint": "请先设置 LARK_APP_ID / LARK_APP_SECRET / LARK_BASE_TOKEN"}
        if not self.client.base_token:
            return {"status": "error", "hint": "LARK_BASE_TOKEN 未配置，无法写多维表格"}

        setup = self.client.ensure_tables()
        result: dict[str, Any] = {"status": "ok", "tables": setup, "synced": {}}
        for name, fn in (
            ("products", self._sync_products),
            ("customers", self._sync_customers),
            ("inquiries", self._sync_inquiries),
            ("sourcing_scores", self._sync_sourcing),
            ("knowledge_base", self._sync_knowledge),
        ):
            try:
                result["synced"][name] = fn()
            except Exception as e:
                logger.warning("同步 %s 失败: %s", name, e)
                result["synced"][name] = {"status": "error", "msg": str(e)[:200]}
        return result

    def _sync_products(self) -> dict[str, Any]:
        with open(SKU_FILE, "r", encoding="utf-8") as f:
            products = json.load(f)["products"]
        records = [{
            "SKU": p["sku"],
            "产品名称": p["name_zh"],
            "英文名称": p.get("name_en"),
            "克重": _num(p.get("gram")),
            "网孔": p.get("mesh_size"),
            "FOB价格USD每平米": _num(p.get("target_price_usd_per_sqm")),
            "MOQ卷": _num(p.get("moq_rolls")),
            "交期天": _num(p.get("lead_time_days")),
            "应用场景": ", ".join(p.get("scenarios", [])),
        } for p in products]
        return self.client.batch_create_records("products", records)

    def _sync_customers(self) -> dict[str, Any]:
        with connect() as conn:
            cur = conn.cursor()
            cur.execute(
                """SELECT name, company, country, email, phone, layer, intent, created_at
                   FROM customers ORDER BY id"""
            )
            rows = cur.fetchall()
        records = [{
            "客户姓名": r[0], "公司": r[1], "国家": r[2], "邮箱": r[3],
            "WhatsApp": r[4], "客户分层": r[5], "来源": r[6],
            "首询日期": str(r[7])[:19],
        } for r in rows]
        return self.client.batch_create_records("customers", records)

    def _sync_inquiries(self) -> dict[str, Any]:
        with connect() as conn:
            cur = conn.cursor()
            cur.execute(
                """SELECT i.id, c.name, c.country, i.sku, i.quantity_rolls, i.quantity_sqm,
                          i.message, i.source, i.status, i.ai_intent, i.created_at
                   FROM inquiries i LEFT JOIN customers c ON i.customer_id = c.id
                   ORDER BY i.id"""
            )
            rows = cur.fetchall()
        records = [{
            "询盘编号": f"INQ-{r[0]}", "客户": r[1], "国家": r[2], "目标SKU": r[3],
            "需求卷数": _num(r[4]), "需求面积": _num(r[5]), "客户留言": r[6],
            "来源": r[7], "状态": r[8], "AI识别意图": r[9],
            "创建时间": str(r[10])[:19],
        } for r in rows]
        return self.client.batch_create_records("inquiries", records)

    def _sync_sourcing(self) -> dict[str, Any]:
        """只同步每个 SKU 的最新一次评分。"""
        with connect() as conn:
            cur = conn.cursor()
            if IS_PG:
                cur.execute(
                    """SELECT DISTINCT ON (sku)
                              sku, score_total, score_market, score_growth, score_fit,
                              score_margin, score_barrier, score_sea, tier,
                              ai_reason, target_market, fetched_at
                       FROM sourcing_scores ORDER BY sku, fetched_at DESC, id DESC"""
                )
            else:
                cur.execute(
                    """SELECT sku, score_total, score_market, score_growth, score_fit,
                              score_margin, score_barrier, score_sea, tier,
                              ai_reason, target_market, fetched_at
                       FROM sourcing_scores
                       WHERE id IN (SELECT MAX(id) FROM sourcing_scores GROUP BY sku)"""
                )
            rows = cur.fetchall()

        name_map = _sku_name_map()
        records = [{
            "日期": str(r[11])[:19], "SKU": r[0], "产品名称": name_map.get(r[0], ""),
            "总分": _num(r[1]), "市场规模": _num(r[2]), "增速": _num(r[3]),
            "产线匹配": _num(r[4]), "毛利率": _num(r[5]), "壁垒": _num(r[6]),
            "出海易度": _num(r[7]), "Tier": r[8],
            "AI推荐理由": r[9], "目标市场": r[10],
        } for r in rows]
        return self.client.batch_create_records("sourcing_scores", records)

    def _sync_knowledge(self) -> dict[str, Any]:
        with open(FAQ_FILE, "r", encoding="utf-8") as f:
            faqs = json.load(f)
        items = faqs.get("faqs", faqs) if isinstance(faqs, dict) else faqs
        records = [{
            "类别": it.get("category"),
            "问题中文": it.get("q_zh") or it.get("question_zh"),
            "问题英文": it.get("q_en") or it.get("question_en"),
            "答案": it.get("a_zh") or it.get("answer_zh") or it.get("a_en") or it.get("answer_en"),
            "意图标签": it.get("intent"),
        } for it in items]
        return self.client.batch_create_records("knowledge_base", records)


def _num(v: Any) -> float | None:
    """多维表格数字字段只接受数值，非数值一律返回 None（会被过滤掉）。"""
    if v is None or isinstance(v, bool):
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def _sku_name_map() -> dict[str, str]:
    try:
        with open(SKU_FILE, "r", encoding="utf-8") as f:
            return {p["sku"]: p["name_zh"] for p in json.load(f)["products"]}
    except Exception:
        return {}


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s %(message)s")
    s = FeishuSync()
    print("=== 飞书连通性 ===")
    print(json.dumps(s.client.ping(), ensure_ascii=False, indent=2))
    if "--sync" in sys.argv:
        print("\n=== 全量同步 ===")
        print(json.dumps(s.sync_all(), ensure_ascii=False, indent=2))
    if "--test-inquiry" in sys.argv:
        print("\n=== 模拟新询盘 ===")
        print(json.dumps(s.trigger_automation("new_inquiry", {
            "inquiry_id": 999, "customer": "测试客户", "company": "Test Co",
            "country": "Saudi Arabia", "email": "test@example.com",
            "sku": "GF-AR-145-44", "qty": 800, "message": "测试询盘",
            "source": "manual-test", "intent": "rfq",
        }), ensure_ascii=False, indent=2))
