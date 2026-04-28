"""每日 8 區 AQI 日報。"""
from __future__ import annotations

import logging
from collections import defaultdict
from datetime import datetime, timedelta

from sqlalchemy import select

from core.db import Database
from core.notifier import TelegramNotifier
from system_b_air.alert import aqi_flag
from system_b_air.models import AQIRecord
from system_b_air.regions import REGIONS

logger = logging.getLogger(__name__)


def build_daily_report(db: Database) -> str:
    """聚合 24 小時內每區的平均 AQI、最大 AQI 與最差站。"""
    cutoff = datetime.now() - timedelta(hours=24)
    lines: list[str] = ["📊 <b>8 區空品 24 小時日報</b>", ""]

    with db.session() as session:
        rows = session.execute(
            select(AQIRecord).where(AQIRecord.publish_time >= cutoff)
        ).scalars().all()

    by_region: dict[str, list[AQIRecord]] = defaultdict(list)
    for r in rows:
        by_region[r.region].append(r)

    for region in REGIONS:
        group = by_region.get(region, [])
        aqis = [r.aqi for r in group if r.aqi is not None]
        if not aqis:
            lines.append(f"⚪ <b>{region}</b>　無資料")
            continue
        avg = sum(aqis) / len(aqis)
        worst = max(
            (r for r in group if r.aqi is not None), key=lambda r: r.aqi or 0
        )
        flag, _ = aqi_flag(avg)
        lines.append(
            f"{flag} <b>{region}</b>　均 AQI {avg:.0f}　"
            f"最高 {worst.aqi:.0f} ({worst.site_name})"
        )

    lines.append("")
    lines.append(f"產製時間：{datetime.now().strftime('%Y-%m-%d %H:%M')}")
    return "\n".join(lines)


def send_daily_report(
    db: Database, notifier: TelegramNotifier, chat_id: str | None = None
) -> bool:
    msg = build_daily_report(db)
    return notifier.send_message(msg, chat_id=chat_id)


if __name__ == "__main__":
    from core import load_settings
    logging.basicConfig(level=logging.INFO)
    s = load_settings()
    db = Database(s.databases.get("air_quality", "data/air_quality.db"))
    if not s.telegram.bot_token:
        print(build_daily_report(db))
    else:
        notifier = TelegramNotifier(s.telegram.bot_token, s.telegram.chat_ids.get("daily"))
        send_daily_report(db, notifier, s.telegram.chat_ids.get("daily"))
