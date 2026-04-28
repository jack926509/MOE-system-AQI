"""每日 8 區 AQI 日報。"""
from __future__ import annotations

import html
import logging
from collections import defaultdict
from dataclasses import dataclass
from datetime import timedelta

from sqlalchemy import select

from core.db import Database
from core.notifier import TelegramNotifier
from core.time_utils import now_taipei
from system_b_air.alert import aqi_flag
from system_b_air.formatting import pad, truncate
from system_b_air.models import AQIRecord
from system_b_air.regions import REGIONS

logger = logging.getLogger(__name__)


@dataclass
class _RegionStat:
    region: str
    avg: float
    peak: float
    peak_site: str
    n: int


def build_daily_report(db: Database) -> str:
    """聚合 24 小時內每區的平均 AQI、最大 AQI 與最差站。"""
    cutoff = now_taipei() - timedelta(hours=24)

    with db.session() as session:
        rows = session.execute(
            select(AQIRecord).where(AQIRecord.publish_time >= cutoff)
        ).scalars().all()

    by_region: dict[str, list[AQIRecord]] = defaultdict(list)
    for r in rows:
        by_region[r.region].append(r)

    stats: list[_RegionStat] = []
    no_data: list[str] = []
    for region in REGIONS:
        group = by_region.get(region, [])
        aqis = [r.aqi for r in group if r.aqi is not None]
        if not aqis:
            no_data.append(region)
            continue
        worst = max(
            (r for r in group if r.aqi is not None), key=lambda r: r.aqi or 0
        )
        stats.append(_RegionStat(
            region=region,
            avg=sum(aqis) / len(aqis),
            peak=worst.aqi or 0.0,
            peak_site=worst.site_name,
            n=len(aqis),
        ))

    # 依平均 AQI 由低到高排序（越前面空品越好）
    stats.sort(key=lambda s: s.avg)

    yesterday = (now_taipei() - timedelta(days=1)).strftime("%Y-%m-%d")
    total_n = sum(s.n for s in stats)
    lines: list[str] = [
        f"📊 <b>全台 24h 空品日報</b>",
        f"<i>{yesterday} ‧ {total_n} 筆觀測</i>",
        "",
    ]

    if stats:
        # 「   」(3) 對應「排 旗 」前段
        table = [
            f"排    {pad('區', 6)} {pad('均', 3, 'right')} "
            f"{pad('高', 3, 'right')}  {pad('最差站', 10)}",
            "──    " + "─" * 6 + " " + "─" * 3 + " " + "─" * 3 + "  " + "─" * 10,
        ]
        for i, s in enumerate(stats, 1):
            flag, _ = aqi_flag(s.avg)
            table.append(
                f"{i:>2} {flag} {pad(s.region, 6)} "
                f"{int(s.avg):>3} {int(s.peak):>3}  "
                f"{pad(truncate(s.peak_site, 10), 10)}"
            )
        lines.append("<pre>" + "\n".join(html.escape(t) for t in table) + "</pre>")

        best = stats[0]
        worst = stats[-1]
        best_flag, best_label = aqi_flag(best.avg)
        worst_flag, worst_label = aqi_flag(worst.avg)
        lines.append("")
        lines.append(
            f"🌟 <b>最佳</b>　{best_flag} {best.region}　"
            f"均 {best.avg:.0f}（{best_label}）"
        )
        lines.append(
            f"⚠️ <b>最差</b>　{worst_flag} {worst.region}　"
            f"均 {worst.avg:.0f}（{worst_label}）"
        )
        lines.append(
            f"　　　　　最高站 {html.escape(worst.peak_site)} "
            f"AQI {worst.peak:.0f}"
        )

    if no_data:
        lines.append("")
        lines.append(f"⚪ 無資料：{ '、'.join(no_data) }")

    lines.append("")
    lines.append(f"🕐 產製 {now_taipei().strftime('%Y-%m-%d %H:%M')}")
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
