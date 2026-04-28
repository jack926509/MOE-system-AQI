"""Telegram 訊息排版工具：CJK 對齊、sparkline、AQI 旗號。

Telegram 用 HTML mode：以 <pre> 渲染等寬字型，能呈現對齊表格。
中文字元在等寬字型佔 2 格，本模組以 East Asian Width 計算實際顯示寬度。
"""
from __future__ import annotations

import unicodedata
from typing import Iterable

# Unicode 8 階方塊，由低到高
_SPARK_BLOCKS = "▁▂▃▄▅▆▇█"


def display_width(s: str) -> int:
    """East Asian Width-aware 顯示寬度（CJK 全形字 = 2，半形 = 1）。"""
    w = 0
    for ch in s:
        ea = unicodedata.east_asian_width(ch)
        w += 2 if ea in ("W", "F") else 1
    return w


def pad(s: str, width: int, align: str = "left") -> str:
    """以顯示寬度為單位 padding；align 可為 left / right / center。"""
    diff = width - display_width(s)
    if diff <= 0:
        return s
    if align == "right":
        return " " * diff + s
    if align == "center":
        l = diff // 2
        r = diff - l
        return " " * l + s + " " * r
    return s + " " * diff


def truncate(s: str, width: int) -> str:
    """超過 width 顯示寬度時尾端截斷。"""
    if display_width(s) <= width:
        return s
    out: list[str] = []
    used = 0
    for ch in s:
        w = 2 if unicodedata.east_asian_width(ch) in ("W", "F") else 1
        if used + w > width:
            break
        out.append(ch)
        used += w
    return "".join(out)


def sparkline(values: Iterable[float | None]) -> str:
    """8 階方塊 sparkline；None 留空格保持對齊。"""
    vals = list(values)
    nums = [v for v in vals if v is not None]
    if not nums:
        return ""
    lo, hi = min(nums), max(nums)
    rng = hi - lo
    out: list[str] = []
    for v in vals:
        if v is None:
            out.append(" ")
            continue
        if rng == 0:
            out.append(_SPARK_BLOCKS[len(_SPARK_BLOCKS) // 2])
        else:
            idx = int((v - lo) / rng * (len(_SPARK_BLOCKS) - 1))
            out.append(_SPARK_BLOCKS[idx])
    return "".join(out)


def fmt_num(value: float | None, spec: str = "", dash: str = "—") -> str:
    """None → dash；否則以 spec 格式化。"""
    if value is None:
        return dash
    return format(value, spec) if spec else str(value)


def trend_arrow(values: Iterable[float | None]) -> tuple[str, float | None]:
    """回傳 (箭頭, 變化量)；至少需 2 個有效值，否則 ("", None)。"""
    nums = [v for v in values if v is not None]
    if len(nums) < 2:
        return "", None
    delta = nums[-1] - nums[0]
    if abs(delta) < 1:
        return "→", delta
    return ("↗" if delta > 0 else "↘"), delta
