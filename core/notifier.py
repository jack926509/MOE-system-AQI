"""Telegram 推播：同步薄殼，bot.py 仍用 PTB async API。"""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

import httpx

logger = logging.getLogger(__name__)


class TelegramNotifier:
    def __init__(self, bot_token: str, default_chat_id: str | None = None) -> None:
        if not bot_token:
            raise ValueError("TelegramNotifier requires non-empty bot_token")
        self.bot_token = bot_token
        self.default_chat_id = default_chat_id
        self.base = f"https://api.telegram.org/bot{bot_token}"
        self._client = httpx.Client(timeout=15.0)

    def get_me(self) -> dict[str, Any]:
        resp = self._client.get(f"{self.base}/getMe")
        resp.raise_for_status()
        return resp.json()

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
        try:
            resp = self._client.post(
                f"{self.base}/sendMessage",
                json={
                    "chat_id": target,
                    "text": text,
                    "parse_mode": parse_mode,
                    "disable_web_page_preview": disable_web_page_preview,
                },
            )
            resp.raise_for_status()
            return True
        except httpx.HTTPError as e:
            logger.error("Telegram sendMessage failed: %s", e)
            return False

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
        try:
            with path.open("rb") as f:
                files = {"document": (path.name, f)}
                data: dict[str, Any] = {"chat_id": target}
                if caption:
                    data["caption"] = caption
                resp = self._client.post(
                    f"{self.base}/sendDocument", data=data, files=files
                )
                resp.raise_for_status()
            return True
        except httpx.HTTPError as e:
            logger.error("Telegram sendDocument failed: %s", e)
            return False

    def close(self) -> None:
        self._client.close()
