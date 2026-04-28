"""清理 N 天前的 raw 紀錄，避免 SQLite 無限長大。

預設保留 90 天 AQIRecord 與 ForecastRecord；AlertLog 全留（量小、有歷史價值）。

用法：
    python scripts/prune_old.py            # 用預設 90 天
    python scripts/prune_old.py --days 60
"""
from __future__ import annotations

import argparse
import logging
from datetime import timedelta

from sqlalchemy import delete

from core import load_settings, now_taipei
from core.db import Database
from system_b_air.models import AQIRecord, ForecastRecord

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s: %(message)s")
logger = logging.getLogger(__name__)


def prune(db: Database, days: int = 90) -> tuple[int, int]:
    cutoff = now_taipei() - timedelta(days=days)
    with db.session() as session:
        aqi_n = session.execute(
            delete(AQIRecord).where(AQIRecord.publish_time < cutoff)
        ).rowcount or 0
        fc_n = session.execute(
            delete(ForecastRecord).where(ForecastRecord.publish_time < cutoff)
        ).rowcount or 0
        session.commit()
    logger.info(
        "Prune: cutoff=%s aqi_deleted=%d forecast_deleted=%d",
        cutoff.isoformat(timespec="seconds"), aqi_n, fc_n,
    )
    return aqi_n, fc_n


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--days", type=int, default=90, help="保留天數（預設 90）")
    args = parser.parse_args()

    settings = load_settings()
    db = Database(settings.databases.get("air_quality", "data/air_quality.db"))
    prune(db, days=args.days)

    # SQLite VACUUM 釋放空間
    with db.engine.connect() as conn:
        conn.exec_driver_sql("VACUUM")
    logger.info("VACUUM done")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
