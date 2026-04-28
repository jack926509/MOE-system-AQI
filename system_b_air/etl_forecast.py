"""空品預報 ETL：拉 aqx_p_434 → ForecastRecord。"""
from __future__ import annotations

import logging
from typing import Any

from sqlalchemy.dialects.sqlite import insert as sqlite_insert

from core import Datasets, MoEnvAPIClient, load_settings
from core.db import Database
from core.time_utils import parse_publishtime
from system_b_air.models import ForecastRecord
from system_b_air.regions import REGIONS, region_alias

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s: %(message)s")
logger = logging.getLogger(__name__)


def _to_row(rec: dict[str, Any]) -> dict[str, Any] | None:
    raw_area = rec.get("area") or rec.get("region") or ""
    region = raw_area.strip()
    if region not in REGIONS:
        # 嘗試別名
        alias = region_alias(region)
        if alias is None:
            return None
        region = alias
    forecast_date = (rec.get("forecastdate") or rec.get("forecast_date") or "").strip()
    publish = parse_publishtime(rec.get("publishtime") or rec.get("publish_time"))
    if not forecast_date or publish is None:
        return None

    return {
        "region": region,
        "forecast_date": forecast_date,
        "publish_time": publish,
        "aqi": (rec.get("aqi") or "").strip() or None,
        "aqi_status": (rec.get("aqi_status") or rec.get("status") or "").strip() or None,
        "minor_pollutant": (rec.get("minorpollutant") or rec.get("minor_pollutant") or "").strip() or None,
        "major_pollutant": (rec.get("majorpollutant") or rec.get("major_pollutant") or "").strip() or None,
        "content": (rec.get("content") or "").strip() or None,
    }


def run_etl() -> int:
    settings = load_settings()
    db = Database(settings.databases.get("air_quality", "data/air_quality.db"))
    db.create_all()

    client = MoEnvAPIClient(
        api_key=settings.moenv.api_key,
        base_url=settings.moenv.base_url,
        page_size=settings.moenv.page_size,
    )
    with client:
        records = client.fetch_all(Datasets.AQI_FORECAST)

    rows = [r for r in (_to_row(rec) for rec in records) if r]
    inserted = 0
    if rows:
        with db.session() as session:
            stmt = sqlite_insert(ForecastRecord).values(rows)
            stmt = stmt.on_conflict_do_nothing(
                index_elements=["region", "forecast_date", "publish_time"]
            )
            result = session.execute(stmt)
            session.commit()
            inserted = result.rowcount or 0

    logger.info(
        "Forecast ETL: fetched=%d valid=%d inserted=%d",
        len(records), len(rows), inserted,
    )
    return inserted


if __name__ == "__main__":
    run_etl()
