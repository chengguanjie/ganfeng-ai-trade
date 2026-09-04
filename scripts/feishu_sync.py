"""
赣丰玻纤 · 飞书同步层（lark-base 适配）
=========================================
把 SQLite 的 5 张表数据按 V4 方案"飞书多维表格"字段定义同步过去。

本模块在演示模式下默认"打印动作不真发"，真实生产环境通过 subprocess 调用 lark-cli。
"""
from __future__ import annotations
import json
import os
import sqlite3
import subprocess
import sys
from datetime import datetime
from typing import Any

THIS_DIR = os.path.dirname(os.path.abspath(__file__))
ROOT_DIR = os.path.dirname(THIS_DIR)
DB_FILE = os.path.join(ROOT_DIR, "data", "trade.db")


# 飞书多维表格字段定义（与 V4 方案严格对应）
FEISHU_BASE_SCHEMA = {
    "products": {
        "fields": [
            {"name": "SKU", "type": "SingleLineText"},
            {"name": "产品名称", "type": "SingleLineText"},
            {"name": "克重 (g/m²)", "type": "Number"},
            {"name": "网孔", "type": "SingleLineText"},
            {"name": "目标市场", "type": "MultiSelect"},
            {"name": "FOB 价格 (USD/m²)", "type": "Number"},
            {"name": "MOQ (卷)", "type": "Number"},
            {"name": "交期 (天)", "type": "Number"},
            {"name": "毛利率 (%)", "type": "Number"},
            {"name": "上线状态", "type": "Select"},
        ]
    },
    "customers": {
        "fields": [
            {"name": "客户姓名", "type": "SingleLineText"},
            {"name": "公司", "type": "SingleLineText"},
            {"name": "国家", "type": "SingleLineText"},
            {"name": "邮箱", "type": "Email"},
            {"name": "WhatsApp", "type": "Phone"},
            {"name": "客户分层", "type": "Select"},
            {"name": "首询日期", "type": "DateTime"},
            {"name": "负责人", "type": "User"},
            {"name": "来源", "type": "Select"},
            {"name": "状态", "type": "Select"},
        ]
    },
    "inquiries": {
        "fields": [
            {"name": "询盘编号", "type": "AutoNumber"},
            {"name": "客户", "type": "Link", "link_to": "customers"},
            {"name": "目标 SKU", "type": "Link", "link_to": "products"},
            {"name": "需求卷数", "type": "Number"},
            {"name": "需求面积 (m²)", "type": "Number"},
            {"name": "客户留言", "type": "MultiLineText"},
            {"name": "来源", "type": "Select"},
            {"name": "状态", "type": "Select"},
            {"name": "AI 识别意图", "type": "SingleLineText"},
            {"name": "客户分层", "type": "Select"},
            {"name": "创建时间", "type": "DateTime"},
            {"name": "跟进人", "type": "User"},
        ]
    },
    "sourcing_scores": {
        "fields": [
            {"name": "日期", "type": "Date"},
            {"name": "SKU", "type": "Link", "link_to": "products"},
            {"name": "总分", "type": "Number"},
            {"name": "市场规模", "type": "Number"},
            {"name": "增速", "type": "Number"},
            {"name": "产线匹配", "type": "Number"},
            {"name": "毛利率", "type": "Number"},
            {"name": "壁垒", "type": "Number"},
            {"name": "出海易度", "type": "Number"},
            {"name": "Tier", "type": "Select"},
            {"name": "推荐理由", "type": "MultiLineText"},
            {"name": "数据源版本", "type": "SingleLineText"},
        ]
    },
    "knowledge_base": {
        "fields": [
            {"name": "类别", "type": "Select"},
            {"name": "问题 (中)", "type": "SingleLineText"},
            {"name": "问题 (英)", "type": "SingleLineText"},
            {"name": "答案", "type": "MultiLineText"},
            {"name": "意图标签", "type": "SingleLineText"},
            {"name": "命中关键词", "type": "MultiLineText"},
            {"name": "状态", "type": "Select"},
        ]
    },
}


class FeishuSync:
    """
    演示模式 (LARK_DRY_RUN=true) ：仅打印，不会真正调用 lark-cli
    真实模式 (LARK_DRY_RUN=false)：调用 lark-base 命令写入字段与记录
    """

    def __init__(self, db_path: str = DB_FILE, dry_run: bool | None = None):
        if dry_run is None:
            dry_run = os.environ.get("LARK_DRY_RUN", "true").lower() != "false"
        self.db_path = db_path
        self.dry_run = dry_run

    def _exec(self, cmd_args: list[str]) -> dict[str, Any]:
        if self.dry_run:
            return {"status": "dry-run", "cmd": "lark-cli " + " ".join(cmd_args[:5]) + " ..."}
        try:
            res = subprocess.run(
                ["lark-cli"] + cmd_args,
                capture_output=True, text=True, check=True, timeout=60,
            )
            return {"status": "ok", "stdout": res.stdout[:500]}
        except subprocess.CalledProcessError as e:
            return {"status": "error", "stderr": e.stderr[:500]}
        except FileNotFoundError:
            return {"status": "lark-cli-not-installed"}

    def ensure_schema(self, base_token: str) -> dict[str, Any]:
        """确保飞书多维表格 5 张主表的字段已存在"""
        results = {}
        for tbl_name, schema in FEISHU_BASE_SCHEMA.items():
            fields_json = json.dumps(schema["fields"], ensure_ascii=False)
            results[tbl_name] = self._exec([
                "base", "field", "create",
                "--base-token", base_token,
                "--table-name", tbl_name,
                "--fields", fields_json,
            ])
        return results

    def push_one_inquiry(self, base_token: str, table_name: str, rec: dict) -> dict[str, Any]:
        cell_values = json.dumps(rec, ensure_ascii=False)
        return self._exec([
            "base", "record", "create",
            "--base-token", base_token,
            "--table-name", table_name,
            "--cell-values", cell_values,
        ])

    def push_recent(self, base_token: str, target_table: str, since_minutes: int = 60) -> dict[str, Any]:
        """把 SQLite 最近 N 分钟的新记录同步到飞书"""
        if not os.path.exists(self.db_path):
            return {"status": "no-local-db"}
        conn = sqlite3.connect(self.db_path)
        cur = conn.cursor()
        results = {"table": target_table, "pushed": 0, "errors": 0, "details": []}

        if target_table == "inquiries":
            rows = cur.execute("""
                SELECT i.id, c.name, i.sku, i.quantity_rolls, i.quantity_sqm, i.message,
                       i.source, i.status, i.created_at
                FROM inquiries i LEFT JOIN customers c ON i.customer_id = c.id
                ORDER BY i.id DESC LIMIT 50
            """).fetchall()
            for row in rows:
                rec = {
                    "客户": row[1] or "匿名",
                    "目标 SKU": row[2],
                    "需求卷数": row[3] or 0,
                    "需求面积 (m²)": row[4] or 0,
                    "客户留言": row[5] or "",
                    "来源": row[6] or "website",
                    "状态": row[7] or "new",
                    "创建时间": row[8],
                }
                r = self.push_one_inquiry(base_token, target_table, rec)
                results["pushed" if r.get("status") == "ok" or r.get("status") == "dry-run" else "errors"] += 1
                results["details"].append(r)
        elif target_table == "customers":
            rows = cur.execute("""
                SELECT id, name, company, country, email, phone, intent, created_at
                FROM customers ORDER BY id DESC LIMIT 50
            """).fetchall()
            for row in rows:
                rec = {
                    "客户姓名": row[1], "公司": row[2], "国家": row[3],
                    "邮箱": row[4], "WhatsApp": row[5], "客户分层": row[6] or "cold",
                    "首询日期": row[7], "状态": "active",
                }
                r = self.push_one_inquiry(base_token, "customers", rec)
                results["pushed" if r.get("status") in ("ok", "dry-run") else "errors"] += 1

        conn.close()
        return results

    def trigger_automation(self, trigger_type: str, payload: dict) -> dict[str, Any]:
        """触发飞书自动化（如：新询盘通知外贸群）"""
        # 真实示例（dry-run=false 时）：
        # self._exec(["im", "messages", "send", "--chat-id", "<外贸群ID>", "--content", json.dumps(...)])
        action = f"automation: {trigger_type} | payload: {json.dumps(payload)[:120]}"
        if self.dry_run:
            print(f"[feishu-dry-run] {action}")
            return {"status": "dry-run", "action": action}
        # 真实环境：调用自动化触发器
        return self._exec(["im", "messages", "send", "--content", action])


if __name__ == "__main__":
    fsync = FeishuSync(dry_run=True)
    print("=== ensure_schema (demo) ===")
    for k, v in fsync.ensure_schema("BASE_TOKEN_DEMO").items():
        print(f"  {k}: {v['status']}")
    print("\n=== trigger_automation ===")
    fsync.trigger_automation("new_inquiry", {"customer": "Ali Mahmoud", "sku": "GF-AR-145-44"})
