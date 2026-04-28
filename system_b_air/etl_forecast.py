"""空品預報 ETL：拉 aqx_p_434 → ForecastRecord。"""
from __future__ import annotations

import logging
from collections import Counter
from typing import Any

from sqlalchemy.dialects.sqlite import insert as sqlite_insert

from core import Datasets, MoEnvAPIClient, load_settings
from core.db import Database
from core.time_utils import parse_publishtime
from system_b_air.models import ForecastRecord
from system_b_air.regions import REGIONS, region_alias

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s: %(message)s")
logger = logging.getLogger(__name__)


def _ci_get(rec: dict[str, Any], *keys: str) -> Any:
    lower = {k.lower(): v for k, v in rec.items()}
    for k in keys:
        v = lower.get(k.lower())
        if v not in (None, ""):
            return v
    return None


def _classify(rec: dict[str, Any]) -> tuple[dict[str, Any] | None, str | None]:
    raw_area = _ci_get(rec, "area", "region") or ""
    region = str(raw_area).strip().replace("台", "臺")
    if region not in REGIONS:
        alias = region_alias(region)
        if alias is None:
            return None, f"unknown_area:{region or 'empty'}"
        region = alias

    forecast_date = (str(_ci_get(rec, "forecastdate", "forecast_date") or "").strip())
    if not forecast_date:
        return None, "no_forecast_date"

    publish = parse_publishtime(_ci_get(rec, "publishtime", "publish_time"))
    if publish is None:
        return None, "bad_publishtime"

    row = {
        "region": region,
        "forecast_date": forecast_date,
        "publish_time": publish,
        "aqi": (str(_ci_get(rec, "aqi") or "").strip() or None),
        "aqi_status": (str(_ci_get(rec, "aqi_status", "status") or "").strip() or None),
        "minor_pollutant": (
            str(_ci_get(rec, "minorpollutant", "minor_pollutant") or "").strip() or None
        ),
        "major_pollutant": (
            str(_ci_get(rec, "majorpollutant", "major_pollutant") or "").strip() or None
        ),
        "content": (str(_ci_get(rec, "content") or "").strip() or None),
    }
    return row, None


def _to_row(rec: dict[str, Any]) -> dict[str, Any] | None:
    row, _ = _classify(rec)
    return row


def run_etl() -> int:
    settings = load_settings()
    if not settings.moenv.api_key:
        logger.error("MoEnv API key 未設定，中止 forecast ETL")
        return 0

    db = Database(settings.databases.get("air_quality", "data/air_quality.db"))
    db.create_all()

    client = MoEnvAPIClient(
        api_key=settings.moenv.api_key,
        base_url=settings.moenv.base_url,
        page_size=settings.moenv.page_size,
        timeout=settings.moenv.timeout,
        max_retries=settings.moenv.max_retries,
    )
    skip_reasons: Counter[str] = Counter()
    with client:
        records = client.fetch_all(Datasets.AQI_FORECAST)

    rows: list[dict[str, Any]] = []
    for rec in records:
        row, reason = _classify(rec)
        if row is None:
            skip_reasons[reason or "unknown"] += 1
            continue
        rows.append(row)

    inserted = 0
    if rows:
        chunk_size = 500
        with db.session() as session:
            for i in range(0, len(rows), chunk_size):
                chunk = rows[i : i + chunk_size]
                stmt = sqlite_insert(ForecastRecord).values(chunk).on_conflict_do_nothing(
                    index_elements=["region", "forecast_date", "publish_time"]
                )
                result = session.execute(stmt)
                rc = result.rowcount or 0
                if rc > 0:
                    inserted += rc
            session.commit()

    if skip_reasons:
        logger.warning("Forecast skipped: %s", dict(skip_reasons))
    logger.info(
        "Forecast ETL: fetched=%d valid=%d inserted=%d",
        len(records), len(rows), inserted,
    )
    return inserted


if __name__ == "__main__":
    run_etl()
