"""
赣丰玻纤 · 飞书开放平台客户端（真实 API）
==========================================

覆盖 V5 方案第 ⑤⑥ 章所需的全部飞书能力：

  1. tenant_access_token 获取与缓存
  2. 多维表格（Bitable）：列表 / 建表 / 建字段 / 写记录
  3. 群消息（IM）：文本 / 卡片通知
  4. 群列表查询（方便你找 chat_id）

需要的环境变量
--------------
  LARK_APP_ID        飞书自建应用 App ID       （必填）
  LARK_APP_SECRET    飞书自建应用 App Secret   （必填）
  LARK_BASE_TOKEN    多维表格 app_token        （必填，写表用）
  LARK_CHAT_ID       接收通知的群 chat_id      （选填，不填则不推群消息）
  LARK_DOMAIN        默认 https://open.feishu.cn（国际版用 open.larksuite.com）
  LARK_DRY_RUN       true 时只打印不发请求      （默认 false）

应用需要的权限（在飞书开发者后台「权限管理」勾选后发布版本）
------------------------------------------------------------
  bitable:app                读写多维表格
  im:message:send_as_bot     以应用身份发消息
  im:chat:readonly           获取群列表（用于查 chat_id）
"""
from __future__ import annotations

import json
import logging
import os
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from typing import Any

logger = logging.getLogger("feishu")

LARK_DOMAIN = os.environ.get("LARK_DOMAIN", "https://open.feishu.cn").rstrip("/")
TIMEOUT = int(os.environ.get("LARK_TIMEOUT", "20"))


def _env(key: str, default: str = "") -> str:
    return (os.environ.get(key) or default).strip()


def is_dry_run() -> bool:
    return _env("LARK_DRY_RUN", "false").lower() == "true"


def is_configured() -> bool:
    """是否具备调用飞书 API 的最低配置。"""
    return bool(_env("LARK_APP_ID") and _env("LARK_APP_SECRET"))


class FeishuError(RuntimeError):
    def __init__(self, code: int, msg: str, path: str):
        super().__init__(f"[{path}] code={code} msg={msg}")
        self.code = code
        self.msg = msg
        self.path = path


# ============================================================
# 底层 HTTP
# ============================================================
def _request(
    method: str,
    path: str,
    *,
    token: str | None = None,
    body: dict | None = None,
    params: dict | None = None,
) -> dict[str, Any]:
    url = f"{LARK_DOMAIN}{path}"
    if params:
        url += "?" + urllib.parse.urlencode(params)

    data = json.dumps(body, ensure_ascii=False).encode("utf-8") if body is not None else None
    headers = {"Content-Type": "application/json; charset=utf-8"}
    if token:
        headers["Authorization"] = f"Bearer {token}"

    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
            payload = json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        raw = e.read().decode("utf-8", errors="replace")
        try:
            payload = json.loads(raw)
        except Exception:
            raise FeishuError(e.code, raw[:300], path) from e
    except Exception as e:
        raise FeishuError(-1, str(e), path) from e

    code = payload.get("code", 0)
    if code != 0:
        raise FeishuError(code, payload.get("msg", "unknown"), path)
    return payload


# ============================================================
# 多维表格字段类型
# ============================================================
FIELD_TEXT = 1
FIELD_NUMBER = 2
FIELD_SINGLE_SELECT = 3
FIELD_MULTI_SELECT = 4
FIELD_DATETIME = 5
FIELD_CHECKBOX = 7
FIELD_USER = 11
FIELD_PHONE = 13
FIELD_URL = 15
FIELD_AUTO_NUMBER = 1005

# V5 方案的 5 张主表结构
TABLE_SCHEMA: dict[str, list[dict[str, Any]]] = {
    "products": [
        {"field_name": "SKU", "type": FIELD_TEXT},
        {"field_name": "产品名称", "type": FIELD_TEXT},
        {"field_name": "英文名称", "type": FIELD_TEXT},
        {"field_name": "克重", "type": FIELD_NUMBER},
        {"field_name": "网孔", "type": FIELD_TEXT},
        {"field_name": "FOB价格USD每平米", "type": FIELD_NUMBER},
        {"field_name": "MOQ卷", "type": FIELD_NUMBER},
        {"field_name": "交期天", "type": FIELD_NUMBER},
        {"field_name": "应用场景", "type": FIELD_TEXT},
    ],
    "customers": [
        {"field_name": "客户姓名", "type": FIELD_TEXT},
        {"field_name": "公司", "type": FIELD_TEXT},
        {"field_name": "国家", "type": FIELD_TEXT},
        {"field_name": "邮箱", "type": FIELD_TEXT},
        {"field_name": "WhatsApp", "type": FIELD_TEXT},
        {"field_name": "客户分层", "type": FIELD_TEXT},
        {"field_name": "来源", "type": FIELD_TEXT},
        {"field_name": "首询日期", "type": FIELD_TEXT},
    ],
    "inquiries": [
        {"field_name": "询盘编号", "type": FIELD_TEXT},
        {"field_name": "客户", "type": FIELD_TEXT},
        {"field_name": "国家", "type": FIELD_TEXT},
        {"field_name": "目标SKU", "type": FIELD_TEXT},
        {"field_name": "需求卷数", "type": FIELD_NUMBER},
        {"field_name": "需求面积", "type": FIELD_NUMBER},
        {"field_name": "客户留言", "type": FIELD_TEXT},
        {"field_name": "来源", "type": FIELD_TEXT},
        {"field_name": "状态", "type": FIELD_TEXT},
        {"field_name": "AI识别意图", "type": FIELD_TEXT},
        {"field_name": "客户分层", "type": FIELD_TEXT},
        {"field_name": "创建时间", "type": FIELD_TEXT},
    ],
    "sourcing_scores": [
        {"field_name": "日期", "type": FIELD_TEXT},
        {"field_name": "SKU", "type": FIELD_TEXT},
        {"field_name": "产品名称", "type": FIELD_TEXT},
        {"field_name": "总分", "type": FIELD_NUMBER},
        {"field_name": "市场规模", "type": FIELD_NUMBER},
        {"field_name": "增速", "type": FIELD_NUMBER},
        {"field_name": "产线匹配", "type": FIELD_NUMBER},
        {"field_name": "毛利率", "type": FIELD_NUMBER},
        {"field_name": "壁垒", "type": FIELD_NUMBER},
        {"field_name": "出海易度", "type": FIELD_NUMBER},
        {"field_name": "Tier", "type": FIELD_TEXT},
        {"field_name": "AI推荐理由", "type": FIELD_TEXT},
        {"field_name": "目标市场", "type": FIELD_TEXT},
    ],
    "knowledge_base": [
        {"field_name": "类别", "type": FIELD_TEXT},
        {"field_name": "问题中文", "type": FIELD_TEXT},
        {"field_name": "问题英文", "type": FIELD_TEXT},
        {"field_name": "答案", "type": FIELD_TEXT},
        {"field_name": "意图标签", "type": FIELD_TEXT},
    ],
}


class FeishuClient:
    """飞书开放平台客户端。线程安全的 token 缓存。"""

    _lock = threading.Lock()

    def __init__(
        self,
        app_id: str | None = None,
        app_secret: str | None = None,
        base_token: str | None = None,
        chat_id: str | None = None,
        dry_run: bool | None = None,
    ):
        self.app_id = app_id or _env("LARK_APP_ID")
        self.app_secret = app_secret or _env("LARK_APP_SECRET")
        self.base_token = base_token or _env("LARK_BASE_TOKEN")
        self.chat_id = chat_id or _env("LARK_CHAT_ID")
        self.dry_run = is_dry_run() if dry_run is None else dry_run
        self._token: str | None = None
        self._token_exp: float = 0.0
        self._table_cache: dict[str, str] = {}

    # ── token ──────────────────────────────────────
    def token(self) -> str:
        """获取 tenant_access_token（带 5 分钟安全边界的缓存）。"""
        with self._lock:
            if self._token and time.time() < self._token_exp:
                return self._token
            if not (self.app_id and self.app_secret):
                raise FeishuError(-1, "LARK_APP_ID / LARK_APP_SECRET 未配置", "token")
            payload = _request(
                "POST",
                "/open-apis/auth/v3/tenant_access_token/internal",
                body={"app_id": self.app_id, "app_secret": self.app_secret},
            )
            self._token = payload["tenant_access_token"]
            self._token_exp = time.time() + max(60, int(payload.get("expire", 7200)) - 300)
            logger.info("tenant_access_token acquired, ttl=%ss", payload.get("expire"))
            return self._token

    def ping(self) -> dict[str, Any]:
        """连通性自检：能否拿到 token、能否读到多维表格。"""
        result: dict[str, Any] = {
            "configured": is_configured(),
            "dry_run": self.dry_run,
            "domain": LARK_DOMAIN,
            "has_base_token": bool(self.base_token),
            "has_chat_id": bool(self.chat_id),
        }
        if not is_configured():
            result["ok"] = False
            result["error"] = "LARK_APP_ID / LARK_APP_SECRET 未配置"
            return result
        try:
            self.token()
            result["token"] = "ok"
        except FeishuError as e:
            result["ok"] = False
            result["error"] = str(e)
            return result

        if self.base_token:
            try:
                tables = self.list_tables()
                result["tables"] = [t["name"] for t in tables]
            except FeishuError as e:
                result["ok"] = False
                result["error"] = f"多维表格访问失败: {e}"
                return result
        result["ok"] = True
        return result

    # ── Bitable ────────────────────────────────────
    def list_tables(self) -> list[dict[str, Any]]:
        payload = _request(
            "GET",
            f"/open-apis/bitable/v1/apps/{self.base_token}/tables",
            token=self.token(),
            params={"page_size": 100},
        )
        return payload.get("data", {}).get("items", [])

    def table_id_map(self, refresh: bool = False) -> dict[str, str]:
        if self._table_cache and not refresh:
            return self._table_cache
        self._table_cache = {t["name"]: t["table_id"] for t in self.list_tables()}
        return self._table_cache

    def create_table(self, name: str, fields: list[dict[str, Any]]) -> str:
        payload = _request(
            "POST",
            f"/open-apis/bitable/v1/apps/{self.base_token}/tables",
            token=self.token(),
            body={"table": {"name": name, "fields": fields}},
        )
        table_id = payload["data"]["table_id"]
        logger.info("table created: %s -> %s", name, table_id)
        return table_id

    def ensure_tables(self) -> dict[str, Any]:
        """确保 V5 的 5 张主表存在；缺的建，已有的跳过。"""
        if self.dry_run:
            return {"status": "dry-run", "would_create": list(TABLE_SCHEMA)}
        if not self.base_token:
            raise FeishuError(-1, "LARK_BASE_TOKEN 未配置", "ensure_tables")

        existing = self.table_id_map(refresh=True)
        created, skipped = [], []
        for name, fields in TABLE_SCHEMA.items():
            if name in existing:
                skipped.append(name)
                continue
            tid = self.create_table(name, fields)
            existing[name] = tid
            created.append(name)
        self._table_cache = existing
        return {"status": "ok", "created": created, "existing": skipped, "tables": existing}

    def create_record(self, table_name: str, fields: dict[str, Any]) -> dict[str, Any]:
        """向指定表写入一条记录。"""
        if self.dry_run:
            logger.info("[dry-run] create_record %s: %s", table_name, json.dumps(fields, ensure_ascii=False)[:200])
            return {"status": "dry-run", "table": table_name}
        tables = self.table_id_map()
        table_id = tables.get(table_name)
        if not table_id:
            # 表不存在则按 schema 自动补建
            if table_name in TABLE_SCHEMA:
                table_id = self.create_table(table_name, TABLE_SCHEMA[table_name])
                self._table_cache[table_name] = table_id
            else:
                raise FeishuError(-1, f"表 {table_name} 不存在且无预定义 schema", "create_record")

        clean = {k: v for k, v in fields.items() if v is not None and v != ""}
        payload = _request(
            "POST",
            f"/open-apis/bitable/v1/apps/{self.base_token}/tables/{table_id}/records",
            token=self.token(),
            body={"fields": clean},
        )
        rec = payload.get("data", {}).get("record", {})
        return {"status": "ok", "record_id": rec.get("record_id"), "table": table_name}

    def batch_create_records(self, table_name: str, records: list[dict[str, Any]]) -> dict[str, Any]:
        """批量写入（单次上限 500 条，自动分批）。"""
        if self.dry_run:
            return {"status": "dry-run", "table": table_name, "count": len(records)}
        if not records:
            return {"status": "ok", "count": 0}
        tables = self.table_id_map()
        table_id = tables.get(table_name)
        if not table_id and table_name in TABLE_SCHEMA:
            table_id = self.create_table(table_name, TABLE_SCHEMA[table_name])
            self._table_cache[table_name] = table_id
        if not table_id:
            raise FeishuError(-1, f"表 {table_name} 不存在", "batch_create_records")

        total = 0
        for i in range(0, len(records), 500):
            chunk = records[i : i + 500]
            body = {"records": [{"fields": {k: v for k, v in r.items() if v is not None and v != ""}} for r in chunk]}
            _request(
                "POST",
                f"/open-apis/bitable/v1/apps/{self.base_token}/tables/{table_id}/records/batch_create",
                token=self.token(),
                body=body,
            )
            total += len(chunk)
        return {"status": "ok", "table": table_name, "count": total}

    # ── IM ─────────────────────────────────────────
    def list_chats(self) -> list[dict[str, Any]]:
        """列出应用所在的群（用来查 chat_id）。"""
        payload = _request(
            "GET",
            "/open-apis/im/v1/chats",
            token=self.token(),
            params={"page_size": 100},
        )
        return [
            {"chat_id": c.get("chat_id"), "name": c.get("name"), "description": c.get("description")}
            for c in payload.get("data", {}).get("items", [])
        ]

    def send_text(self, text: str, chat_id: str | None = None) -> dict[str, Any]:
        target = chat_id or self.chat_id
        if self.dry_run:
            logger.info("[dry-run] send_text -> %s: %s", target, text[:150])
            return {"status": "dry-run", "text": text[:150]}
        if not target:
            return {"status": "skipped", "reason": "LARK_CHAT_ID 未配置"}
        _request(
            "POST",
            "/open-apis/im/v1/messages",
            token=self.token(),
            params={"receive_id_type": "chat_id"},
            body={
                "receive_id": target,
                "msg_type": "text",
                "content": json.dumps({"text": text}, ensure_ascii=False),
            },
        )
        return {"status": "ok", "chat_id": target}

    def send_card(self, title: str, lines: list[str], chat_id: str | None = None,
                  color: str = "blue") -> dict[str, Any]:
        """发送交互卡片（新询盘通知用）。"""
        target = chat_id or self.chat_id
        if self.dry_run:
            logger.info("[dry-run] send_card -> %s: %s | %s", target, title, " / ".join(lines)[:150])
            return {"status": "dry-run", "title": title}
        if not target:
            return {"status": "skipped", "reason": "LARK_CHAT_ID 未配置"}

        card = {
            "config": {"wide_screen_mode": True},
            "header": {
                "title": {"tag": "plain_text", "content": title},
                "template": color,
            },
            "elements": [
                {"tag": "div", "text": {"tag": "lark_md", "content": "\n".join(lines)}},
            ],
        }
        _request(
            "POST",
            "/open-apis/im/v1/messages",
            token=self.token(),
            params={"receive_id_type": "chat_id"},
            body={
                "receive_id": target,
                "msg_type": "interactive",
                "content": json.dumps(card, ensure_ascii=False),
            },
        )
        return {"status": "ok", "chat_id": target}


# 进程级单例，避免重复取 token
_client: FeishuClient | None = None


def get_client() -> FeishuClient:
    global _client
    if _client is None:
        _client = FeishuClient()
    return _client


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    c = FeishuClient()
    print("=== ping ===")
    print(json.dumps(c.ping(), ensure_ascii=False, indent=2))
    if c.ping().get("ok") and c.base_token:
        print("\n=== ensure_tables ===")
        print(json.dumps(c.ensure_tables(), ensure_ascii=False, indent=2))
        print("\n=== chats ===")
        try:
            print(json.dumps(c.list_chats(), ensure_ascii=False, indent=2))
        except FeishuError as e:
            print(f"（需要 im:chat:readonly 权限）{e}")
