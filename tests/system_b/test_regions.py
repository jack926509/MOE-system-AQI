from system_b_air.regions import (
    REGIONS,
    REGION_COUNTIES,
    all_counties,
    county_to_region,
    normalize_county,
    region_alias,
)


def test_normalize_county():
    assert normalize_county("台中市") == "臺中市"
    assert normalize_county("臺中市") == "臺中市"
    assert normalize_county("  臺中市  ") == "臺中市"
    assert normalize_county(None) == ""


def test_county_to_region_taiwanese_variants():
    assert county_to_region("臺中市") == "中部"
    assert county_to_region("台中市") == "中部"


def test_county_to_region_all_counties_mapped():
    for c in all_counties():
        assert county_to_region(c) is not None, f"{c} 未對應到區"


def test_county_to_region_unknown():
    assert county_to_region("北海道") is None


def test_region_alias():
    assert region_alias("北部") == "北部"
    assert region_alias("北") == "北部"
    assert region_alias("中") == "中部"
    assert region_alias("雲嘉") == "雲嘉南"
    assert region_alias("離島") == "離島"
    assert region_alias("xxx") is None


def test_regions_count_8():
    assert len(REGIONS) == 8
    assert set(REGION_COUNTIES.keys()) == set(REGIONS)
