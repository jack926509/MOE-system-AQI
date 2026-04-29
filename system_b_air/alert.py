"""空品告警：站層級主、區層級輔。"""
from __future__ import annotations

import logging
import re
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Iterable

from sqlalchemy import func, select
from sqlalchemy.dialects.sqlite import insert as sqlite_insert

from core.config import StationAlertThresholds, RegionAlertThresholds
from core.db import Database
from core.notifier import TelegramNotifier
from core.time_utils import now_taipei
from system_b_air.models import AlertLog, AQIRecord
from system_b_air.regions import REGION_COUNTIES

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

# 污染物顯示單位（對齊環境部 aqx_p_432 欄位單位）
_POLLUTANT_UNITS: dict[str, str] = {
    "pm25": "μg/m³",
    "pm10": "μg/m³",
    "so2": "ppb",
    "no2": "ppb",
    "o3": "ppb",
    "co": "ppm",
}

# 主污染物中文 → 顯示用短碼（即時 ETL 回傳中文，UI 縮寫好讀）
POLLUTANT_ABBR: dict[str, str] = {
    "細懸浮微粒": "PM2.5",
    "懸浮微粒": "PM10",
    "臭氧": "O₃",
    "臭氧八小時": "O₃",
    "二氧化氮": "NO₂",
    "二氧化硫": "SO₂",
    "一氧化碳": "CO",
}


def pollutant_short(name: str | None) -> str:
    """主污染物中文 → 短碼；查不到回原字串。空值回 '—'。"""
    if not name:
        return "—"
    s = name.strip()
    return POLLUTANT_ABBR.get(s, s)


def aqi_flag(aqi: float | None) -> tuple[str, str]:
    if aqi is None:
        return ("⚪", "無資料")
    for limit, flag, label in AQI_FLAGS:
        if aqi <= limit:
            return (flag, label)
    return ("🟤", "危害")


def aqi_flag_from_str(value: str | None) -> tuple[str, str]:
    """預報的 AQI 欄位是字串、可能是區間「100~150」；取較高端代表整體風險。"""
    if not value:
        return ("⚪", "無資料")
    s = str(value).strip()
    if not s:
        return ("⚪", "無資料")
    nums = re.findall(r"\d+", s)
    if not nums:
        return ("⚪", "無資料")
    return aqi_flag(float(nums[-1]))


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
    plant: str | None = None  # 命中電廠周界 watchlist 才有值

    def to_message(self) -> str:
        import html as _html
        ts = self.publish_time.strftime("%Y-%m-%d %H:%M")
        plant_line = (
            f"⚡ <b>{_html.escape(self.plant)} 周界站</b>"
            if self.plant else None
        )
        loc = (
            f"{_html.escape(self.region)} ‧ {_html.escape(self.site_name)}"
            if self.scope == "station" and self.site_name
            else f"{_html.escape(self.region)}（區域）"
        )

        if self.pollutant == "aqi":
            flag, label = aqi_flag(self.value)
            title = "區域空品超標" if self.scope == "region" else "空品達告警標準"
            lines = [f"{flag} <b>{title}</b>"]
            if plant_line:
                lines.append(plant_line)
            lines += [
                f"📍 {loc}",
                f"AQI <b>{self.value:.0f}</b>　{label}",
                f"警戒值 {self.threshold:.0f}",
                f"🕐 {ts}",
            ]
            if self.scope == "station" and self.site_name:
                lines.append(
                    f"\n<i>📈 走勢 → /trend {_html.escape(self.site_name)}</i>"
                )
            else:
                lines.append(
                    f"\n<i>🗺️ 區內細節 → /aqi {_html.escape(self.region)}</i>"
                )
            return "\n".join(lines)

        unit = _POLLUTANT_UNITS.get(self.pollutant, "")
        # 數值精度：ppb 用整數、ppm 兩位、μg/m³ 一位
        if unit == "ppb":
            val_fmt = f"{self.value:.0f}"
            th_fmt = f"{self.threshold:.0f}"
        elif unit == "ppm":
            val_fmt = f"{self.value:.2f}"
            th_fmt = f"{self.threshold:.2f}"
        else:
            val_fmt = f"{self.value:.1f}"
            th_fmt = f"{self.threshold:.1f}"
        name = self.pollutant.upper()
        lines = [f"⚠️ <b>{name} 超標</b>"]
        if plant_line:
            lines.append(plant_line)
        lines += [
            f"📍 {loc}",
            f"{name} <b>{val_fmt}</b> {unit}",
            f"警戒值 {th_fmt} {unit}",
            f"🕐 {ts}",
        ]
        if self.scope == "station" and self.site_name:
            lines.append(
                f"\n<i>📈 走勢 → /trend {_html.escape(self.site_name)}</i>"
            )
        return "\n".join(lines)


def _check_station(
    record: AQIRecord,
    th: StationAlertThresholds,
    plant_map: dict[str, str] | None = None,
) -> list[AlertEvent]:
    events: list[AlertEvent] = []
    plant = (plant_map or {}).get(record.site_name)
    # 各污染物比對；threshold 為 None 視為停用
    pairs: list[tuple[str, float | None, float | None]] = [
        ("aqi", record.aqi, th.aqi),
        ("pm25", record.pm25, th.pm25),
        ("so2", record.so2, th.so2),
        ("no2", record.no2, th.no2),
        ("co", record.co, getattr(th, "co", None)),
        ("o3", record.o3, getattr(th, "o3", None)),
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
                    plant=plant,
                )
            )
    return events


# 8 區應有站數推估：以縣市數 × 1.x 倍當粗略 baseline，但實務取「歷史曾觀測過的站數」更準
# 為避免引入額外查詢，先用「該區當前可見站數 + 一個保底下限」混合：分母 = max(可見站數, baseline)
_REGION_STATION_BASELINE: dict[str, int] = {
    # 依環境部 88 站歷史分布（北部 22、竹苗 5、中部 12、雲嘉南 17、高屏 17、宜蘭 3、花東 6、離島 6）
    "北部": 22,
    "竹苗": 5,
    "中部": 12,
    "雲嘉南": 17,
    "高屏": 17,
    "宜蘭": 3,
    "花東": 6,
    "離島": 6,
}


def _check_region(
    records: Iterable[AQIRecord], th: RegionAlertThresholds
) -> list[AlertEvent]:
    """同一掃描批次內某區 ≥ ratio 的站 AQI 超標時，產生一則區級事件。

    分母用「max(可見有 AQI 站數, 該區 baseline)」，避免多數站故障造成 1/1 = 100% 誤觸發。
    """
    by_region: dict[str, list[AQIRecord]] = defaultdict(list)
    for r in records:
        by_region[r.region].append(r)

    events: list[AlertEvent] = []
    for region, group in by_region.items():
        with_aqi = [g for g in group if g.aqi is not None]
        if not with_aqi:
            continue
        bad = [g for g in with_aqi if g.aqi >= th.aqi]
        if not bad:
            continue
        baseline = _REGION_STATION_BASELINE.get(region, len(REGION_COUNTIES.get(region, ())))
        denom = max(len(with_aqi), baseline)
        ratio = len(bad) / denom
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
        # 限縮在這批事件可能撞到的時間 / 範圍，避免全表掃描
        publish_times = {k[3] for k in keys}
        targets = {k[1] for k in keys}
        existing_rows = session.execute(
            select(
                AlertLog.scope,
                AlertLog.target,
                AlertLog.pollutant,
                AlertLog.publish_time,
            ).where(
                AlertLog.publish_time.in_(publish_times),
                AlertLog.target.in_(targets),
            )
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


def _latest_per_site(db: Database, fresh_hours: int = 2) -> list[AQIRecord]:
    """每站取最新一筆，且 publish_time >= now - fresh_hours。

    取代舊版「全表最新 publish_time」邏輯，避免站點因延遲 publish 被漏掉。
    """
    cutoff = now_taipei() - timedelta(hours=fresh_hours)
    with db.session() as session:
        # 子查詢：每個 site_name 最新 publish_time
        max_pub = (
            select(
                AQIRecord.site_name.label("sn"),
                func.max(AQIRecord.publish_time).label("mp"),
            )
            .where(AQIRecord.publish_time >= cutoff)
            .group_by(AQIRecord.site_name)
            .subquery()
        )
        rows = session.execute(
            select(AQIRecord)
            .join(
                max_pub,
                (AQIRecord.site_name == max_pub.c.sn)
                & (AQIRecord.publish_time == max_pub.c.mp),
            )
        ).scalars().all()
    return list(rows)


def run_alerts(
    db: Database,
    notifier: TelegramNotifier | None,
    station_th: StationAlertThresholds,
    region_th: RegionAlertThresholds,
    chat_id: str | None = None,
    fresh_hours: int = 2,
    plant_map: dict[str, str] | None = None,
    admin_chat_id: str | None = None,
) -> int:
    """掃描每站最新且 fresh_hours 內的 AQI，發站＋區告警。

    plant_map：site_name → 電廠名，命中者標註並複本推送 admin（若有）。
    """
    rows = _latest_per_site(db, fresh_hours=fresh_hours)
    if not rows:
        logger.info("No fresh AQI record (within %dh), skip alert", fresh_hours)
        return 0

    events: list[AlertEvent] = []
    for r in rows:
        events.extend(_check_station(r, station_th, plant_map=plant_map))
    events.extend(_check_region(rows, region_th))

    new_events = _persist_dedup(db, events)
    plant_hits = 0
    if notifier and new_events:
        for ev in new_events:
            msg = ev.to_message()
            notifier.send_message(msg, chat_id=chat_id)
            # 周界站事件複本發 admin（若 admin_chat_id 與 alert 不同）
            if ev.plant and admin_chat_id and admin_chat_id != chat_id:
                notifier.send_message(msg, chat_id=admin_chat_id)
                plant_hits += 1
    logger.info(
        "Alert: scanned=%d events=%d new=%d plant=%d",
        len(rows), len(events), len(new_events), plant_hits,
    )
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
        plant_map=s.station_to_plant(),
        admin_chat_id=s.telegram.chat_ids.get("admin"),
    )
