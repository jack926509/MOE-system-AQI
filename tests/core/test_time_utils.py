from datetime import datetime

from core.time_utils import parse_minguo_date, parse_publishtime


def test_parse_publishtime_iso():
    assert parse_publishtime("2024-08-15 14:00") == datetime(2024, 8, 15, 14, 0)


def test_parse_publishtime_slash():
    assert parse_publishtime("2024/08/15 14:00:30") == datetime(2024, 8, 15, 14, 0, 30)


def test_parse_publishtime_iso_t():
    assert parse_publishtime("2024-08-15T14:00:00") == datetime(2024, 8, 15, 14, 0)


def test_parse_publishtime_empty():
    assert parse_publishtime("") is None
    assert parse_publishtime(None) is None


def test_parse_minguo_year():
    assert parse_minguo_date("113-05-23") == datetime(2024, 5, 23)
    assert parse_minguo_date("113/05/23") == datetime(2024, 5, 23)
    assert parse_minguo_date("113年05月23日") == datetime(2024, 5, 23)
    assert parse_minguo_date("1130523") == datetime(2024, 5, 23)


def test_parse_minguo_invalid():
    assert parse_minguo_date(None) is None
    assert parse_minguo_date("") is None
