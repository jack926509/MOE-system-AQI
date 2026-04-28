"""freshness 模組：watchlist 站台連續 N 小時無資料 → 通報。"""
import tempfile
from datetime import timedelta
from pathlib import Path

from core.db import Database
from core.time_utils import now_taipei
from system_b_air.freshness import _dedup_and_persist, find_stale_sites
from system_b_air.models import AQIRecord


def _add_record(db: Database, site: str, ts) -> None:
    with db.session() as s:
        s.add(AQIRecord(
            site_name=site, region="北部", county="桃園市",
            publish_time=ts, aqi=50,
        ))
        s.commit()


def test_find_stale_returns_sites_with_old_or_no_data():
    with tempfile.TemporaryDirectory() as d:
        db = Database(str(Path(d) / "x.db"))
        db.create_all()
        now = now_taipei()
        _add_record(db, "大園", now - timedelta(minutes=30))   # 新鮮
        _add_record(db, "龍潭", now - timedelta(hours=4))      # 失聯
        # 觀音 沒有任何資料

        stale = find_stale_sites(db, ["大園", "龍潭", "觀音"], stale_hours=3)
        names = {s for s, _ in stale}
        assert "大園" not in names
        assert "龍潭" in names
        assert "觀音" in names


def test_find_stale_empty_watchlist_returns_empty():
    with tempfile.TemporaryDirectory() as d:
        db = Database(str(Path(d) / "x.db"))
        db.create_all()
        assert find_stale_sites(db, [], stale_hours=3) == []


def test_dedup_and_persist_skips_repeats():
    with tempfile.TemporaryDirectory() as d:
        db = Database(str(Path(d) / "x.db"))
        db.create_all()
        ts = now_taipei() - timedelta(hours=4)
        items = [("龍潭", ts)]
        first = _dedup_and_persist(db, items)
        assert len(first) == 1
        # 同一 (site, last_pub) 第二次不該再進
        second = _dedup_and_persist(db, items)
        assert second == []
