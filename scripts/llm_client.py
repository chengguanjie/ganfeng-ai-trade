"""
赣丰玻纤 · DeepSeek LLM 客户端
================================

DeepSeek API 兼容 OpenAI 接口格式：
  Base URL: https://api.deepseek.com/v1
  Model:    deepseek-chat
  Auth:     Bearer <api_key>

提供：
  - chat_completion(messages, temperature, max_tokens) → str
  - 自动从环境变量读取 DEEPSEEK_API_KEY
  - 超时 / 重试 / 降级处理
"""
from __future__ import annotations

import json
import os
import time
import logging
from typing import Any

logger = logging.getLogger("llm")

# ── 配置 ──────────────────────────────────────────
DEEPSEEK_API_KEY = os.environ.get(
    "DEEPSEEK_API_KEY",
    "",
)
DEEPSEEK_BASE_URL = os.environ.get("DEEPSEEK_BASE_URL", "https://api.deepseek.com/v1")
DEEPSEEK_MODEL = os.environ.get("DEEPSEEK_MODEL", "deepseek-chat")
TIMEOUT = int(os.environ.get("DEEPSEEK_TIMEOUT", "30"))
MAX_RETRIES = 2


def _raw_chat(messages: list[dict], temperature: float = 0.7, max_tokens: int = 800) -> str | None:
    """直接 HTTP 调用 DeepSeek，不依赖 openai SDK"""
    import urllib.request
    import urllib.error

    url = f"{DEEPSEEK_BASE_URL}/chat/completions"
    payload = json.dumps({
        "model": DEEPSEEK_MODEL,
        "messages": messages,
        "temperature": temperature,
        "max_tokens": max_tokens,
        "stream": False,
    }).encode("utf-8")

    req = urllib.request.Request(
        url,
        data=payload,
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {DEEPSEEK_API_KEY}",
        },
        method="POST",
    )

    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
            body = json.loads(resp.read().decode("utf-8"))
            return body["choices"][0]["message"]["content"]
    except urllib.error.HTTPError as e:
        err_body = e.read().decode("utf-8", errors="replace")
        logger.error("DeepSeek HTTP %d: %s", e.code, err_body[:300])
        return None
    except Exception as e:
        logger.error("DeepSeek request failed: %s", e)
        return None


def chat_completion(
    messages: list[dict[str, str]],
    temperature: float = 0.7,
    max_tokens: int = 800,
) -> str | None:
    """
    调用 DeepSeek Chat API。

    Args:
        messages: OpenAI 格式 [{"role":"system","content":"..."},{"role":"user","content":"..."}]
        temperature: 0-2
        max_tokens: 输出上限

    Returns:
        LLM 回复文本，失败返回 None
    """
    for attempt in range(MAX_RETRIES + 1):
        result = _raw_chat(messages, temperature, max_tokens)
        if result is not None:
            return result.strip()
        if attempt < MAX_RETRIES:
            time.sleep(1.5 * (attempt + 1))
    return None


def is_available() -> bool:
    """快速检查 API key 是否配置"""
    return bool(DEEPSEEK_API_KEY) and DEEPSEEK_API_KEY.startswith("sk-")


if __name__ == "__main__":
    # 快速测试
    print(f"API Key: {DEEPSEEK_API_KEY[:10]}...")
    print(f"Base URL: {DEEPSEEK_BASE_URL}")
    print(f"Model: {DEEPSEEK_MODEL}")
    print("\n--- Test call ---")
    msg = chat_completion(
        [
            {"role": "system", "content": "You are a helpful assistant. Reply in 1 sentence."},
            {"role": "user", "content": "Say hello in Chinese."},
        ],
        temperature=0.3,
        max_tokens=50,
    )
    print(f"Response: {msg}")
