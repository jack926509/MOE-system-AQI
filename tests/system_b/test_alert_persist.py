import tempfile
from datetime import datetime
from pathlib import Path

from core.db import Database
from system_b_air.alert import AlertEvent, _persist_dedup
from system_b_air.models import AlertLog  # noqa: F401  ensure ORM register


def _ev(scope: str, target: str, pollutant: str, ts: datetime, value: float = 160) -> AlertEvent:
    return AlertEvent(
        scope=scope, target=target, pollutant=pollutant,
        value=value, threshold=150, publish_time=ts,
        region="中部",
        site_name=target if scope == "station" else None,
    )


def test_persist_dedup_filters_duplicates_within_batch():
    with tempfile.TemporaryDirectory() as d:
        db = Database(str(Path(d) / "x.db"))
        db.create_all()
        ts = datetime(2024, 8, 15, 14, 0)
        events = [
            _ev("station", "沙鹿", "aqi", ts),
            _ev("station", "沙鹿", "aqi", ts),  # 同 batch 重複
            _ev("station", "西屯", "aqi", ts),
        ]
        new = _persist_dedup(db, events)
        assert {e.target for e in new} == {"沙鹿", "西屯"}
        # 第二次跑：全部都已存在，應無新增
        new2 = _persist_dedup(db, events)
        assert new2 == []


def test_persist_dedup_distinguishes_by_publish_time():
    with tempfile.TemporaryDirectory() as d:
        db = Database(str(Path(d) / "x.db"))
        db.create_all()
        e1 = _ev("station", "沙鹿", "aqi", datetime(2024, 8, 15, 14, 0))
        e2 = _ev("station", "沙鹿", "aqi", datetime(2024, 8, 15, 15, 0))
        new = _persist_dedup(db, [e1, e2])
        assert len(new) == 2


def test_persist_dedup_empty():
    with tempfile.TemporaryDirectory() as d:
        db = Database(str(Path(d) / "x.db"))
        db.create_all()
        assert _persist_dedup(db, []) == []
