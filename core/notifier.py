"""Telegram 推播：同步薄殼，bot.py 仍用 PTB async API。

特性：
- 4096 字訊息自動切分（依 \\n 邊界，HTML 友善）
- 5xx / 429 自動重試，並遵守 retry_after
- 連線錯誤指數退避
"""
from __future__ import annotations

import logging
import time
from pathlib import Path
from typing import Any

import httpx

logger = logging.getLogger(__name__)

# Telegram message hard limit
_TG_LIMIT = 4096
# 預留 HTML closing tag / safety margin
_CHUNK_SAFE = 3900


def _split_for_telegram(text: str, limit: int = _CHUNK_SAFE) -> list[str]:
    """以換行為界拆分長訊息；每段 <= limit。"""
    if len(text) <= limit:
        return [text]
    chunks: list[str] = []
    buf: list[str] = []
    size = 0
    for line in text.split("\n"):
        # 單行過長：硬切
        if len(line) > limit:
            if buf:
                chunks.append("\n".join(buf))
                buf, size = [], 0
            for i in range(0, len(line), limit):
                chunks.append(line[i : i + limit])
            continue
        # +1 是換行
        if size + len(line) + 1 > limit and buf:
            chunks.append("\n".join(buf))
            buf, size = [], 0
        buf.append(line)
        size += len(line) + 1
    if buf:
        chunks.append("\n".join(buf))
    return chunks


class TelegramNotifier:
    def __init__(
        self,
        bot_token: str,
        default_chat_id: str | None = None,
        max_retries: int = 3,
    ) -> None:
        if not bot_token:
            raise ValueError("TelegramNotifier requires non-empty bot_token")
        self.bot_token = bot_token
        self.default_chat_id = default_chat_id
        self.max_retries = max_retries
        self.base = f"https://api.telegram.org/bot{bot_token}"
        self._client = httpx.Client(timeout=15.0)

    def get_me(self) -> dict[str, Any]:
        resp = self._client.get(f"{self.base}/getMe")
        resp.raise_for_status()
        return resp.json()

    def _post_with_retry(
        self,
        path: str,
        *,
        json: dict[str, Any] | None = None,
        data: dict[str, Any] | None = None,
        files: dict[str, Any] | None = None,
    ) -> bool:
        url = f"{self.base}/{path}"
        for attempt in range(1, self.max_retries + 1):
            try:
                resp = self._client.post(url, json=json, data=data, files=files)
                if resp.status_code == 429:
                    # Telegram rate limit
                    retry_after = 1.0
                    try:
                        retry_after = float(
                            resp.json().get("parameters", {}).get("retry_after", 1)
                        )
                    except Exception:
                        pass
                    logger.warning(
                        "Telegram 429, sleep %.1fs (attempt %d)", retry_after, attempt
                    )
                    time.sleep(retry_after)
                    continue
                if 500 <= resp.status_code < 600:
                    logger.warning(
                        "Telegram %s 5xx %s (attempt %d)", path, resp.status_code, attempt
                    )
                    time.sleep(min(2 ** attempt, 8))
                    continue
                if 400 <= resp.status_code < 500:
                    # 400/401/403：通常為 chat_id 錯、bot 被踢、parse_mode 錯，重試無益
                    body_preview = resp.text[:200].replace("\n", " ")
                    logger.error(
                        "Telegram %s %s (no retry): %s",
                        path, resp.status_code, body_preview,
                    )
                    return False
                resp.raise_for_status()
                return True
            except (httpx.TimeoutException, httpx.TransportError) as e:
                logger.warning("Telegram %s net err: %s (attempt %d)", path, e, attempt)
                if attempt == self.max_retries:
                    logger.error("Telegram %s give up after %d attempts", path, attempt)
                    return False
                time.sleep(min(2 ** attempt, 8))
            except httpx.HTTPError as e:
                logger.error("Telegram %s err (no retry): %s", path, e)
                return False
        return False

    def send_message(
        self,
        text: str,
        chat_id: str | None = None,
        parse_mode: str = "HTML",
        disable_web_page_preview: bool = True,
    ) -> bool:
        target = chat_id or self.default_chat_id
        if not target:
            raise ValueError("send_message: 須提供 chat_id 或 default_chat_id")
        chunks = _split_for_telegram(text)
        ok = True
        for chunk in chunks:
            ok &= self._post_with_retry(
                "sendMessage",
                json={
                    "chat_id": target,
                    "text": chunk,
                    "parse_mode": parse_mode,
                    "disable_web_page_preview": disable_web_page_preview,
                },
            )
        return ok

    def send_document(
        self,
        path: str | Path,
        chat_id: str | None = None,
        caption: str | None = None,
    ) -> bool:
        target = chat_id or self.default_chat_id
        if not target:
            raise ValueError("send_document: 須提供 chat_id 或 default_chat_id")
        path = Path(path)
        if not path.exists():
            raise FileNotFoundError(path)
        with path.open("rb") as f:
            files = {"document": (path.name, f)}
            data: dict[str, Any] = {"chat_id": target}
            if caption:
                data["caption"] = caption
            return self._post_with_retry("sendDocument", data=data, files=files)

    def close(self) -> None:
        self._client.close()
