from system_b_air.bot import _parse_hours
from system_b_air.formatting import fmt_num as _fmt


def test_fmt_none():
    assert _fmt(None) == "—"
    assert _fmt(None, ".1f") == "—"


def test_fmt_zero_kept():
    # 0 應顯示 0 而非 —
    assert _fmt(0) == "0"
    assert _fmt(0.0, ".1f") == "0.0"


def test_fmt_value_with_spec():
    assert _fmt(12.345, ".1f") == "12.3"


def test_parse_hours_default():
    site, hours = _parse_hours(["沙鹿"])
    assert site == "沙鹿"
    assert hours == 24


def test_parse_hours_explicit():
    site, hours = _parse_hours(["沙鹿", "12"])
    assert site == "沙鹿"
    assert hours == 12


def test_parse_hours_clamped_to_default_when_invalid():
    site, hours = _parse_hours(["沙鹿", "9999"])
    # 超過 max_hours 視為測站名一部分
    assert site == "沙鹿 9999"
    assert hours == 24


def test_parse_hours_non_numeric_last_arg_kept():
    site, hours = _parse_hours(["A", "B"])
    assert site == "A B"
    assert hours == 24


def test_parse_hours_empty():
    site, hours = _parse_hours([])
    assert site == ""
    assert hours == 24
