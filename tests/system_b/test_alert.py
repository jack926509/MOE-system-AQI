from datetime import datetime

from core.config import RegionAlertThresholds, StationAlertThresholds
from system_b_air.alert import _check_region, _check_station, aqi_flag
from system_b_air.models import AQIRecord


def _rec(site: str, region: str, aqi=None, pm25=None, so2=None, no2=None):
    return AQIRecord(
        site_name=site, region=region, county="臺中市",
        publish_time=datetime(2024, 8, 15, 14, 0),
        aqi=aqi, pm25=pm25, so2=so2, no2=no2,
    )


def test_aqi_flag_levels():
    assert aqi_flag(30)[1] == "良好"
    assert aqi_flag(80)[1] == "普通"
    assert aqi_flag(120)[1] == "對敏感族群不健康"
    assert aqi_flag(180)[1] == "對所有族群不健康"
    assert aqi_flag(None)[1] == "無資料"


def test_station_alert_aqi_hit():
    th = StationAlertThresholds(aqi=150)
    events = _check_station(_rec("沙鹿", "中部", aqi=170), th)
    assert any(e.pollutant == "aqi" and e.target == "沙鹿" for e in events)


def test_station_alert_no_hit():
    th = StationAlertThresholds(aqi=150)
    events = _check_station(_rec("沙鹿", "中部", aqi=80), th)
    assert events == []


def test_region_alert_threshold():
    th = RegionAlertThresholds(aqi=150, ratio=0.3)
    rows = [
        _rec("a", "中部", aqi=160),
        _rec("b", "中部", aqi=170),
        _rec("c", "中部", aqi=80),
        _rec("d", "中部", aqi=90),
    ]
    events = _check_region(rows, th)
    # 2/4 = 0.5 ≥ 0.3 → 應有區事件
    assert any(e.scope == "region" and e.target == "中部" for e in events)


def test_region_alert_below_ratio():
    th = RegionAlertThresholds(aqi=150, ratio=0.3)
    rows = [
        _rec("a", "中部", aqi=170),
        _rec("b", "中部", aqi=80),
        _rec("c", "中部", aqi=90),
        _rec("d", "中部", aqi=85),
    ]
    events = _check_region(rows, th)
    # 1/4 = 0.25 < 0.3 → 沒有區事件
    assert events == []
