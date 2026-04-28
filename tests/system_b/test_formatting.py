from system_b_air.formatting import (
    display_width,
    fmt_num,
    pad,
    sparkline,
    trend_arrow,
    truncate,
)


def test_display_width_ascii():
    assert display_width("hello") == 5
    assert display_width("") == 0


def test_display_width_cjk():
    assert display_width("中文") == 4         # 全形 ×2
    assert display_width("a中b") == 4         # 1+2+1
    assert display_width("沙鹿") == 4
    assert display_width("北部") == 4


def test_pad_left_default():
    out = pad("北部", 6)
    assert display_width(out) == 6
    assert out.startswith("北部")


def test_pad_right():
    out = pad("中", 4, "right")
    assert display_width(out) == 4
    assert out.endswith("中")


def test_pad_no_change_when_wider():
    out = pad("北部", 2)  # already 4 wide
    assert out == "北部"


def test_truncate_keeps_short():
    assert truncate("沙鹿", 8) == "沙鹿"


def test_truncate_cuts_long():
    out = truncate("非常非常非常非常長", 6)
    assert display_width(out) <= 6


def test_truncate_ascii():
    assert truncate("station_name_abc", 10) == "station_na"


def test_sparkline_basic():
    s = sparkline([1, 2, 3, 4, 5])
    assert len(s) == 5
    # 最低值對應最低方塊，最高值對應最高方塊
    assert s[0] == "▁"
    assert s[-1] == "█"


def test_sparkline_handles_none():
    s = sparkline([1, None, 3])
    assert len(s) == 3
    assert s[1] == " "


def test_sparkline_empty():
    assert sparkline([]) == ""
    assert sparkline([None, None]) == ""


def test_sparkline_flat():
    # 全部相等時不該炸 ZeroDivision，回中段方塊
    s = sparkline([50, 50, 50])
    assert len(s) == 3
    assert s.count(s[0]) == 3


def test_fmt_num():
    assert fmt_num(None) == "—"
    assert fmt_num(None, ".1f") == "—"
    assert fmt_num(0) == "0"
    assert fmt_num(0.0, ".1f") == "0.0"
    assert fmt_num(12.345, ".1f") == "12.3"


def test_trend_arrow_up():
    arrow, delta = trend_arrow([50, 60, 75, 90])
    assert arrow == "↗"
    assert delta == 40


def test_trend_arrow_down():
    arrow, delta = trend_arrow([100, 80, 60])
    assert arrow == "↘"
    assert delta == -40


def test_trend_arrow_flat():
    arrow, delta = trend_arrow([50, 50.3, 50.5])
    assert arrow == "→"


def test_trend_arrow_too_few():
    arrow, delta = trend_arrow([50])
    assert arrow == ""
    assert delta is None
    assert trend_arrow([None, None])[0] == ""
