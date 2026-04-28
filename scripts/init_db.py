"""建立空品 SQLite schema。

用法：
    python scripts/init_db.py
"""
from __future__ import annotations

import logging

from core import Database, load_settings

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s: %(message)s")
logger = logging.getLogger(__name__)


def main() -> int:
    settings = load_settings()
    db_path = settings.databases.get("air_quality", "data/air_quality.db")
    import system_b_air.models  # noqa: F401  triggers ORM registration
    Database(db_path).create_all()
    logger.info("✓ air quality DB → %s", db_path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
