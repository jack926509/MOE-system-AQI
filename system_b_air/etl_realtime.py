"""空品即時 ETL：拉 aqx_p_432 → AQIRecord。

用法：
    python -m system_b_air.etl_realtime
"""
from __future__ import annotations

import logging
from typing import Any

from sqlalchemy.dialects.sqlite import insert as sqlite_insert

from core import Datasets, MoEnvAPIClient, load_settings
from core.db import Database
from core.time_utils import parse_publishtime
from system_b_air.models import AQIRecord
from system_b_air.regions import county_to_region, normalize_county

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s: %(message)s")
logger = logging.getLogger(__name__)


def _safe_float(v: Any) -> float | None:
    if v is None or v == "" or v == "ND" or v == "-" or v == "x":
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def _to_row(rec: dict[str, Any]) -> dict[str, Any] | None:
    site_name = (rec.get("sitename") or rec.get("site_name") or "").strip()
    raw_county = rec.get("county") or rec.get("county_name") or ""
    county = normalize_county(raw_county)
    region = county_to_region(county)
    publish = parse_publishtime(rec.get("publishtime") or rec.get("publish_time"))
    if not site_name or not county or not region or publish is None:
        return None

    return {
        "site_id": rec.get("siteid") or rec.get("site_id"),
        "site_name": site_name,
        "county": county,
        "region": region,
        "publish_time": publish,
        "aqi": _safe_float(rec.get("aqi")),
        "pm25": _safe_float(rec.get("pm2.5") or rec.get("pm25")),
        "pm10": _safe_float(rec.get("pm10")),
        "o3": _safe_float(rec.get("o3")),
        "so2": _safe_float(rec.get("so2")),
        "no2": _safe_float(rec.get("no2")),
        "co": _safe_float(rec.get("co")),
        "pollutant": (rec.get("pollutant") or "").strip() or None,
        "status": (rec.get("status") or "").strip() or None,
    }


def run_etl() -> int:
    settings = load_settings()
    db = Database(settings.databases.get("air_quality", "data/air_quality.db"))
    db.create_all()

    client = MoEnvAPIClient(
        api_key=settings.moenv.api_key,
        base_url=settings.moenv.base_url,
        page_size=settings.moenv.page_size,
        timeout=settings.moenv.timeout,
    )
    inserted = 0
    skipped = 0
    with client:
        records = client.fetch_all(Datasets.AQI_REALTIME)

    rows: list[dict[str, Any]] = []
    for rec in records:
        row = _to_row(rec)
        if row is None:
            skipped += 1
            continue
        rows.append(row)

    if rows:
        chunk_size = 500
        with db.session() as session:
            for i in range(0, len(rows), chunk_size):
                chunk = rows[i : i + chunk_size]
                stmt = sqlite_insert(AQIRecord).values(chunk).on_conflict_do_nothing(
                    index_elements=["site_name", "publish_time"]
                )
                result = session.execute(stmt)
                rc = result.rowcount or 0
                if rc > 0:
                    inserted += rc
            session.commit()

    logger.info(
        "AQI realtime ETL: fetched=%d valid=%d inserted=%d skipped=%d",
        len(records),
        len(rows),
        inserted,
        skipped,
    )
    return inserted


if __name__ == "__main__":
    run_etl()
