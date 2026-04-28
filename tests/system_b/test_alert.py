from datetime import datetime

from core.config import RegionAlertThresholds, StationAlertThresholds
from system_b_air.alert import _check_region, _check_station, aqi_flag
from system_b_air.models import AQIRecord


def _rec(site, region, aqi=None, pm25=None, so2=None, no2=None, co=None, o3=None):
    return AQIRecord(
        site_name=site, region=region, county="臺中市",
        publish_time=datetime(2024, 8, 15, 14, 0),
        aqi=aqi, pm25=pm25, so2=so2, no2=no2, co=co, o3=o3,
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


def test_station_alert_so2_uses_ppb_threshold():
    """SO2 環境部回傳 ppb；75 ppb 是 1hr 標準。背景 5 ppb 不該觸發、80 ppb 該觸發。"""
    th = StationAlertThresholds(so2=75)
    assert _check_station(_rec("興達", "高屏", so2=5), th) == []
    hit = _check_station(_rec("興達", "高屏", so2=80), th)
    assert any(e.pollutant == "so2" for e in hit)


def test_station_alert_no2_uses_ppb_threshold():
    th = StationAlertThresholds(no2=100)
    assert _check_station(_rec("沙鹿", "中部", no2=20), th) == []
    hit = _check_station(_rec("沙鹿", "中部", no2=120), th)
    assert any(e.pollutant == "no2" for e in hit)


def test_station_alert_co_and_o3():
    th = StationAlertThresholds(co=9, o3=100)
    hit = _check_station(_rec("沙鹿", "中部", co=10, o3=130), th)
    pollutants = {e.pollutant for e in hit}
    assert "co" in pollutants
    assert "o3" in pollutants


def test_station_plant_tag_passed_through():
    th = StationAlertThresholds(aqi=150)
    plant_map = {"大園": "大潭"}
    events = _check_station(
        _rec("大園", "北部", aqi=180), th, plant_map=plant_map
    )
    assert events
    assert events[0].plant == "大潭"


def test_region_alert_above_baseline():
    """新規則：分母採該區 baseline，避免少數站故障時誤觸發。
    中部 baseline=12，需 ≥ 4 站超標（4/12 = 0.33 ≥ 0.3）。"""
    th = RegionAlertThresholds(aqi=150, ratio=0.3)
    rows = [
        _rec(f"s{i}", "中部", aqi=170) for i in range(4)
    ] + [
        _rec(f"ok{i}", "中部", aqi=80) for i in range(8)
    ]
    events = _check_region(rows, th)
    assert any(e.scope == "region" and e.target == "中部" for e in events)


def test_region_alert_minority_no_trigger():
    """2/12 = 0.17 < 0.3 → 不觸發；舊版會誤判 2/4 = 0.5 觸發。"""
    th = RegionAlertThresholds(aqi=150, ratio=0.3)
    rows = [
        _rec("a", "中部", aqi=170),
        _rec("b", "中部", aqi=170),
        _rec("c", "中部", aqi=80),
        _rec("d", "中部", aqi=90),
    ]
    events = _check_region(rows, th)
    assert events == []


def test_region_alert_below_ratio():
    th = RegionAlertThresholds(aqi=150, ratio=0.3)
    rows = [
        _rec("a", "中部", aqi=170),
        _rec("b", "中部", aqi=80),
        _rec("c", "中部", aqi=90),
        _rec("d", "中部", aqi=85),
    ]
    events = _check_region(rows, th)
    # 1/12 = 0.08 < 0.3 → 沒有區事件
    assert events == []
