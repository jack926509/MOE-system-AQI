"""電廠 watchlist 設定解析。"""
from core.config import _build_settings


def test_plants_dict_form_parsed():
    settings = _build_settings({
        "plants": {
            "大潭": {"counties": ["桃園市"], "stations": ["大園", "龍潭"]},
            "台中": {"counties": ["臺中市"], "stations": ["沙鹿"]},
        }
    })
    assert {p.name for p in settings.plants} == {"大潭", "台中"}
    plant_map = settings.station_to_plant()
    assert plant_map["大園"] == "大潭"
    assert plant_map["龍潭"] == "大潭"
    assert plant_map["沙鹿"] == "台中"


def test_plants_list_form_parsed():
    settings = _build_settings({
        "plants": [
            {"name": "興達", "stations": ["小港", "林園"]},
            {"name": "嘉惠", "stations": ["新港"]},
        ]
    })
    assert {p.name for p in settings.plants} == {"興達", "嘉惠"}
    assert settings.station_to_plant()["小港"] == "興達"


def test_plants_empty_when_absent():
    settings = _build_settings({})
    assert settings.plants == []
    assert settings.station_to_plant() == {}


def test_station_to_plant_first_wins_on_overlap():
    settings = _build_settings({
        "plants": {
            "甲廠": {"stations": ["共用站"]},
            "乙廠": {"stations": ["共用站"]},
        }
    })
    plant_map = settings.station_to_plant()
    # dict 順序 = yaml 載入順序，第一個勝
    assert plant_map["共用站"] == "甲廠"
