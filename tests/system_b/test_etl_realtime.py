from datetime import datetime

from system_b_air.etl_realtime import _safe_float, _to_row


def test_safe_float():
    assert _safe_float("12.3") == 12.3
    assert _safe_float("ND") is None
    assert _safe_float("-") is None
    assert _safe_float("") is None
    assert _safe_float(None) is None
    assert _safe_float("x") is None


def test_to_row_basic():
    row = _to_row({
        "sitename": "沙鹿",
        "county": "台中市",   # 使用「台」字
        "publishtime": "2024-08-15 14:00",
        "aqi": "160",
        "pm2.5": "60",
        "pollutant": "細懸浮微粒",
        "status": "對敏感族群不健康",
    })
    assert row is not None
    assert row["site_name"] == "沙鹿"
    assert row["county"] == "臺中市"   # normalize 過
    assert row["region"] == "中部"
    assert row["aqi"] == 160.0
    assert row["pm25"] == 60.0


def test_to_row_unknown_county():
    row = _to_row({
        "sitename": "x", "county": "UNKNOWN",
        "publishtime": "2024-08-15 14:00",
    })
    assert row is None


def test_to_row_missing_publishtime():
    row = _to_row({"sitename": "x", "county": "臺中市", "publishtime": ""})
    assert row is None
