"""空品即時 ETL：拉 aqx_p_432 → AQIRecord。

用法：
    python -m system_b_air.etl_realtime
"""
from __future__ import annotations

import logging
from collections import Counter
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
    if v is None:
        return None
    if isinstance(v, str):
        s = v.strip()
        if s in ("", "ND", "-", "x", "N/A", "n/a", "NA"):
            return None
        try:
            return float(s)
        except ValueError:
            return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def _ci_get(rec: dict[str, Any], *keys: str) -> Any:
    """取出第一個非空值；忽略大小寫，處理「pm2.5/pm2_5/pm25」等變體。"""
    lower = {k.lower(): v for k, v in rec.items()}
    for k in keys:
        v = lower.get(k.lower())
        if v not in (None, ""):
            return v
    return None


def _classify(rec: dict[str, Any]) -> tuple[dict[str, Any] | None, str | None]:
    """轉成 ORM dict；失敗時回 (None, 跳過原因)。"""
    site_name = (_ci_get(rec, "sitename", "site_name") or "")
    if isinstance(site_name, str):
        site_name = site_name.strip()
    if not site_name:
        return None, "no_sitename"

    raw_county = _ci_get(rec, "county", "county_name") or ""
    county = normalize_county(str(raw_county))
    if not county:
        return None, "no_county"

    region = county_to_region(county)
    if not region:
        return None, f"unknown_county:{county}"

    publish = parse_publishtime(_ci_get(rec, "publishtime", "publish_time"))
    if publish is None:
        return None, "bad_publishtime"

    row = {
        "site_id": _ci_get(rec, "siteid", "site_id"),
        "site_name": site_name,
        "county": county,
        "region": region,
        "publish_time": publish,
        "aqi": _safe_float(_ci_get(rec, "aqi")),
        "pm25": _safe_float(_ci_get(rec, "pm2.5", "pm2_5", "pm25")),
        "pm10": _safe_float(_ci_get(rec, "pm10")),
        "o3": _safe_float(_ci_get(rec, "o3")),
        "so2": _safe_float(_ci_get(rec, "so2")),
        "no2": _safe_float(_ci_get(rec, "no2")),
        "co": _safe_float(_ci_get(rec, "co")),
        "pollutant": (str(_ci_get(rec, "pollutant") or "").strip() or None),
        "status": (str(_ci_get(rec, "status") or "").strip() or None),
    }
    return row, None


def _to_row(rec: dict[str, Any]) -> dict[str, Any] | None:
    """向後相容：只回 row，丟棄 skip 原因。"""
    row, _ = _classify(rec)
    return row


def run_etl() -> int:
    settings = load_settings()
    if not settings.moenv.api_key:
        logger.error("MoEnv API key 未設定（MOENV_API_KEY 或 settings.moenv.api_key），中止 ETL")
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
    inserted = 0
    skip_reasons: Counter[str] = Counter()
    with client:
        records = client.fetch_all(Datasets.AQI_REALTIME)

    rows: list[dict[str, Any]] = []
    for rec in records:
        row, reason = _classify(rec)
        if row is None:
            skip_reasons[reason or "unknown"] += 1
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

    if skip_reasons:
        logger.warning("AQI realtime skipped: %s", dict(skip_reasons))
    logger.info(
        "AQI realtime ETL: fetched=%d valid=%d inserted=%d skipped=%d",
        len(records),
        len(rows),
        inserted,
        sum(skip_reasons.values()),
    )
    return inserted


if __name__ == "__main__":
    run_etl()
