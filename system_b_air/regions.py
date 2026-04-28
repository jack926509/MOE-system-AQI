"""環保署 8 區 county↔region 映射 + 「臺/台」normalize。

預報資料 aqx_p_434 直接帶 area 欄位（值即為 8 區之一）；
即時資料 aqx_p_432 只有 county，需用本表回推。
"""
from __future__ import annotations

# 8 區規範化名稱（顯示用）
REGIONS: tuple[str, ...] = (
    "北部",
    "竹苗",
    "中部",
    "雲嘉南",
    "高屏",
    "宜蘭",
    "花東",
    "離島",
)

# region → counties（顯示時用「臺」字型）
REGION_COUNTIES: dict[str, tuple[str, ...]] = {
    "北部": ("基隆市", "臺北市", "新北市", "桃園市"),
    "竹苗": ("新竹市", "新竹縣", "苗栗縣"),
    "中部": ("臺中市", "彰化縣", "南投縣"),
    "雲嘉南": ("雲林縣", "嘉義市", "嘉義縣", "臺南市"),
    "高屏": ("高雄市", "屏東縣"),
    "宜蘭": ("宜蘭縣",),
    "花東": ("花蓮縣", "臺東縣"),
    "離島": ("澎湖縣", "金門縣", "連江縣"),
}


def normalize_county(name: str | None) -> str:
    """將「台」統一為「臺」、去空白；空字串/None 回傳空字串。"""
    if not name:
        return ""
    return name.strip().replace("台", "臺")


# county → region（用 normalize 後的 key）
_COUNTY_TO_REGION: dict[str, str] = {
    normalize_county(c): region
    for region, counties in REGION_COUNTIES.items()
    for c in counties
}


def county_to_region(county: str | None) -> str | None:
    """county（容忍臺/台、前後空白）→ 8 區之一；查不到回 None。"""
    return _COUNTY_TO_REGION.get(normalize_county(county))


def region_alias(name: str | None) -> str | None:
    """使用者輸入容忍：『北』、『北部』、『竹苗』、『離島』均回 8 區規範名。"""
    if not name:
        return None
    s = name.strip().replace("台", "臺")
    if s in REGIONS:
        return s
    short_alias = {
        "北": "北部",
        "中": "中部",
        "南": "雲嘉南",
        "雲嘉": "雲嘉南",
        "南部": "雲嘉南",
        "高": "高屏",
        "屏": "高屏",
        "東": "花東",
        "花蓮": "花東",
        "臺東": "花東",
        "離": "離島",
        "蘭": "宜蘭",
    }
    return short_alias.get(s)


def all_counties() -> list[str]:
    """88 站常見 county 列表（規範化臺）。"""
    return [c for counties in REGION_COUNTIES.values() for c in counties]
