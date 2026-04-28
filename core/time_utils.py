"""時間解析：環境部 publishtime 與民國年容錯。"""
from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import Optional

try:
    from zoneinfo import ZoneInfo
    TAIPEI_TZ = ZoneInfo("Asia/Taipei")
except Exception:  # pragma: no cover - fallback if tzdata 缺失
    TAIPEI_TZ = timezone.utc


def now_taipei() -> datetime:
    """回傳台北當地時間（naive；與 DB 內 publishtime 同基準便於比較）。"""
    return datetime.now(TAIPEI_TZ).replace(tzinfo=None)

# 常見格式
_FMT_CANDIDATES = (
    "%Y-%m-%d %H:%M",
    "%Y-%m-%d %H:%M:%S",
    "%Y/%m/%d %H:%M",
    "%Y/%m/%d %H:%M:%S",
    "%Y-%m-%d",
    "%Y/%m/%d",
)


def parse_publishtime(raw: str | None) -> Optional[datetime]:
    """環境部資料常見的 publishtime 字串轉 datetime（無時區，視為當地時間）。"""
    if not raw:
        return None
    s = raw.strip()
    if not s:
        return None
    # ISO 8601
    try:
        if "T" in s:
            return datetime.fromisoformat(s.replace("Z", "+00:00"))
    except ValueError:
        pass
    for fmt in _FMT_CANDIDATES:
        try:
            return datetime.strptime(s, fmt)
        except ValueError:
            continue
    return None


_MINGUO_PATTERNS = (
    re.compile(r"^(\d{2,3})[年/-](\d{1,2})[月/-](\d{1,2})日?$"),
    re.compile(r"^(\d{2,3})(\d{2})(\d{2})$"),  # 1130523 → 民國 113 年
)


def parse_minguo_date(raw: str | None) -> Optional[datetime]:
    """民國年字串轉 datetime；接受 113/05/23、113-05-23、113年05月23日、1130523。"""
    if not raw:
        return None
    s = raw.strip()
    if not s:
        return None
    for pat in _MINGUO_PATTERNS:
        m = pat.match(s)
        if not m:
            continue
        try:
            year_minguo = int(m.group(1))
            month = int(m.group(2))
            day = int(m.group(3))
            year = year_minguo + 1911
            return datetime(year, month, day)
        except (ValueError, TypeError):
            continue
    # 作為西元年容錯
    return parse_publishtime(s)


def to_iso(dt: datetime | None) -> str:
    if dt is None:
        return ""
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.isoformat()
