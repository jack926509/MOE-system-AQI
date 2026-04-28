"""空品告警：站層級主、區層級輔。"""
from __future__ import annotations

import logging
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime
from typing import Iterable

from sqlalchemy import select
from sqlalchemy.dialects.sqlite import insert as sqlite_insert

from core.config import StationAlertThresholds, RegionAlertThresholds
from core.db import Database
from core.notifier import TelegramNotifier
from system_b_air.models import AlertLog, AQIRecord

logger = logging.getLogger(__name__)

# AQI 旗號表（顏色＋等級）
AQI_FLAGS: list[tuple[float, str, str]] = [
    (50, "🟢", "良好"),
    (100, "🟡", "普通"),
    (150, "🟠", "對敏感族群不健康"),
    (200, "🔴", "對所有族群不健康"),
    (300, "🟣", "非常不健康"),
    (500, "🟤", "危害"),
]

# 污染物顯示單位（與 settings.example.yaml 一致）
_POLLUTANT_UNITS: dict[str, str] = {
    "pm25": "μg/m³",
    "pm10": "μg/m³",
    "so2": "ppm",
    "no2": "ppm",
    "o3": "ppb",
    "co": "ppm",
}


def aqi_flag(aqi: float | None) -> tuple[str, str]:
    if aqi is None:
        return ("⚪", "無資料")
    for limit, flag, label in AQI_FLAGS:
        if aqi <= limit:
            return (flag, label)
    return ("🟤", "危害")


@dataclass
class AlertEvent:
    scope: str             # 'station' | 'region'
    target: str            # site_name 或 region 名
    pollutant: str
    value: float
    threshold: float
    publish_time: datetime
    region: str
    site_name: str | None = None

    def to_message(self) -> str:
        head = f"[{self.region}]"
        if self.scope == "station" and self.site_name:
            head += f"[{self.site_name}]"
        ts = self.publish_time.strftime("%Y-%m-%d %H:%M")
        if self.pollutant == "aqi":
            flag, label = aqi_flag(self.value)
            scope_label = "區域空品警示" if self.scope == "region" else "空氣品質警示"
            return (
                f"{flag} <b>{head} {scope_label}</b>\n"
                f"AQI = <b>{self.value:.0f}</b> ({label})，閾值 {self.threshold:.0f}\n"
                f"時間 {ts}"
            )
        unit = _POLLUTANT_UNITS.get(self.pollutant, "")
        return (
            f"⚠️ <b>{head} {self.pollutant.upper()} 超標</b>\n"
            f"{self.pollutant.upper()} = <b>{self.value:.2f}</b> {unit}，"
            f"閾值 {self.threshold:.2f} {unit}\n"
            f"時間 {ts}"
        )


def _check_station(
    record: AQIRecord, th: StationAlertThresholds
) -> list[AlertEvent]:
    events: list[AlertEvent] = []
    pairs = [
        ("aqi", record.aqi, th.aqi),
        ("pm25", record.pm25, th.pm25),
        ("so2", record.so2, th.so2),
        ("no2", record.no2, th.no2),
    ]
    for pollutant, value, threshold in pairs:
        if value is None or threshold is None:
            continue
        if value >= threshold:
            events.append(
                AlertEvent(
                    scope="station",
                    target=record.site_name,
                    site_name=record.site_name,
                    region=record.region,
                    pollutant=pollutant,
                    value=value,
                    threshold=threshold,
                    publish_time=record.publish_time,
                )
            )
    return events


def _check_region(
    records: Iterable[AQIRecord], th: RegionAlertThresholds
) -> list[AlertEvent]:
    """同小時內某區 ≥ ratio 的站 AQI 超標時，產生一則區級事件。"""
    by_region: dict[str, list[AQIRecord]] = defaultdict(list)
    for r in records:
        if r.aqi is not None:
            by_region[r.region].append(r)

    events: list[AlertEvent] = []
    for region, group in by_region.items():
        n = len(group)
        if n == 0:
            continue
        bad = [g for g in group if g.aqi is not None and g.aqi >= th.aqi]
        if not bad:
            continue
        ratio = len(bad) / n
        if ratio < th.ratio:
            continue
        worst = max(bad, key=lambda r: r.aqi or 0)
        events.append(
            AlertEvent(
                scope="region",
                target=region,
                region=region,
                pollutant="aqi",
                value=worst.aqi or 0.0,
                threshold=th.aqi,
                publish_time=worst.publish_time,
            )
        )
    return events


def _persist_dedup(
    db: Database, events: list[AlertEvent]
) -> list[AlertEvent]:
    """寫入 AlertLog，重複者過濾掉。

    使用單次 SELECT 找出已存在的 dedup key，再 batch insert 新事件，
    避免每事件一次 commit 造成 N+1 round-trip。
    """
    if not events:
        return []

    with db.session() as session:
        keys = {(e.scope, e.target, e.pollutant, e.publish_time) for e in events}
        existing_rows = session.execute(
            select(
                AlertLog.scope,
                AlertLog.target,
                AlertLog.pollutant,
                AlertLog.publish_time,
            ).where(AlertLog.scope.in_({k[0] for k in keys}))
        ).all()
        existing = {tuple(row) for row in existing_rows}

        seen: set[tuple[str, str, str, datetime]] = set()
        new_events: list[AlertEvent] = []
        rows: list[dict] = []
        for ev in events:
            key = (ev.scope, ev.target, ev.pollutant, ev.publish_time)
            if key in existing or key in seen:
                continue
            seen.add(key)
            new_events.append(ev)
            rows.append(
                dict(
                    scope=ev.scope,
                    target=ev.target,
                    pollutant=ev.pollutant,
                    value=ev.value,
                    threshold=ev.threshold,
                    publish_time=ev.publish_time,
                )
            )

        if rows:
            stmt = sqlite_insert(AlertLog).values(rows).on_conflict_do_nothing(
                index_elements=["scope", "target", "pollutant", "publish_time"]
            )
            session.execute(stmt)
            session.commit()

    return new_events


def run_alerts(
    db: Database,
    notifier: TelegramNotifier | None,
    station_th: StationAlertThresholds,
    region_th: RegionAlertThresholds,
    chat_id: str | None = None,
) -> int:
    """掃描最新一輪 publish_time 的 AQI，發站＋區告警。"""
    with db.session() as session:
        latest = session.execute(
            select(AQIRecord.publish_time).order_by(AQIRecord.publish_time.desc()).limit(1)
        ).scalar_one_or_none()
        if latest is None:
            logger.info("No AQI record yet, skip alert")
            return 0
        rows = session.execute(
            select(AQIRecord).where(AQIRecord.publish_time == latest)
        ).scalars().all()

    events: list[AlertEvent] = []
    for r in rows:
        events.extend(_check_station(r, station_th))
    events.extend(_check_region(rows, region_th))

    new_events = _persist_dedup(db, events)
    if notifier and new_events:
        for ev in new_events:
            notifier.send_message(ev.to_message(), chat_id=chat_id)
    logger.info("Alert: scanned=%d events=%d new=%d", len(rows), len(events), len(new_events))
    return len(new_events)


if __name__ == "__main__":
    from core import load_settings
    logging.basicConfig(level=logging.INFO)
    s = load_settings()
    db = Database(s.databases.get("air_quality", "data/air_quality.db"))
    notifier = (
        TelegramNotifier(s.telegram.bot_token, s.telegram.chat_ids.get("alert"))
        if s.telegram.bot_token
        else None
    )
    run_alerts(
        db, notifier,
        s.air_quality_alerts.station,
        s.air_quality_alerts.region,
        chat_id=s.telegram.chat_ids.get("alert"),
    )
