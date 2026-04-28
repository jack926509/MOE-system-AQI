"""系統 B SQLAlchemy ORM。"""
from __future__ import annotations

from datetime import datetime

from sqlalchemy import Float, Index, Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from core.db import Base


class AQIRecord(Base):
    """aqx_p_432 即時 AQI（每站每小時一筆）。"""

    __tablename__ = "aqi_records"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    site_id: Mapped[str | None] = mapped_column(String(32), index=True)
    site_name: Mapped[str] = mapped_column(String(64), index=True)
    county: Mapped[str] = mapped_column(String(32), index=True)
    region: Mapped[str] = mapped_column(String(16), index=True)  # 8 區之一
    publish_time: Mapped[datetime] = mapped_column(index=True)

    aqi: Mapped[float | None] = mapped_column(Float)
    pm25: Mapped[float | None] = mapped_column(Float)
    pm10: Mapped[float | None] = mapped_column(Float)
    o3: Mapped[float | None] = mapped_column(Float)
    so2: Mapped[float | None] = mapped_column(Float)
    no2: Mapped[float | None] = mapped_column(Float)
    co: Mapped[float | None] = mapped_column(Float)
    pollutant: Mapped[str | None] = mapped_column(String(32))   # 主污染物
    status: Mapped[str | None] = mapped_column(String(16))      # 良好/普通/...

    __table_args__ = (
        UniqueConstraint("site_name", "publish_time", name="uq_site_publish"),
        Index("ix_region_publish", "region", "publish_time"),
    )


class AlertLog(Base):
    """告警去重 log：相同 (site_name, pollutant, publish_time) 一小時內只發一次。"""

    __tablename__ = "alert_logs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    scope: Mapped[str] = mapped_column(String(8), index=True)        # 'station' | 'region'
    target: Mapped[str] = mapped_column(String(64), index=True)      # site_name 或 region
    pollutant: Mapped[str] = mapped_column(String(16))
    value: Mapped[float | None] = mapped_column(Float)
    threshold: Mapped[float | None] = mapped_column(Float)
    publish_time: Mapped[datetime] = mapped_column(index=True)
    sent_at: Mapped[datetime] = mapped_column(default=datetime.utcnow)

    __table_args__ = (
        UniqueConstraint(
            "scope", "target", "pollutant", "publish_time", name="uq_alert_dedup"
        ),
    )


class ForecastRecord(Base):
    """aqx_p_434 預報（已含 area 欄位＝8 區）。"""

    __tablename__ = "forecast_records"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    region: Mapped[str] = mapped_column(String(16), index=True)
    forecast_date: Mapped[str] = mapped_column(String(16), index=True)  # 預報日 YYYY-MM-DD
    publish_time: Mapped[datetime] = mapped_column(index=True)
    aqi: Mapped[str | None] = mapped_column(String(16))         # 可能是區間「100~150」
    aqi_status: Mapped[str | None] = mapped_column(String(16))
    minor_pollutant: Mapped[str | None] = mapped_column(String(32))
    major_pollutant: Mapped[str | None] = mapped_column(String(32))
    content: Mapped[str | None] = mapped_column(String(512))    # 描述

    __table_args__ = (
        UniqueConstraint(
            "region", "forecast_date", "publish_time", name="uq_region_forecast"
        ),
    )
