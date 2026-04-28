"""一次性把 bot 命令清單寫入 Telegram。

用法：
    python -m scripts.set_commands           # 註冊
    python -m scripts.set_commands --clear   # 清空（命令選單不再顯示）
"""
from __future__ import annotations

import argparse
import asyncio
import logging

from telegram import Bot

from core import load_settings
from system_b_air.bot import BOT_COMMANDS

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s: %(message)s")
logger = logging.getLogger(__name__)


async def _run(clear: bool) -> None:
    settings = load_settings()
    token = settings.telegram.bot_token
    if not token:
        raise SystemExit("settings.telegram.bot_token 未設定")

    bot = Bot(token=token)
    async with bot:
        if clear:
            await bot.delete_my_commands()
            logger.info("已清空 Telegram 命令清單")
            return
        await bot.set_my_commands(BOT_COMMANDS)
        for c in BOT_COMMANDS:
            logger.info("  /%s — %s", c.command, c.description)
        logger.info("完成：已註冊 %d 個命令", len(BOT_COMMANDS))


def main() -> None:
    parser = argparse.ArgumentParser(description="同步 bot 命令清單到 Telegram")
    parser.add_argument("--clear", action="store_true", help="清空命令選單")
    args = parser.parse_args()
    asyncio.run(_run(args.clear))


if __name__ == "__main__":
    main()
