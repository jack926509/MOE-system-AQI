"""設定載入：YAML + .env 變數展開。"""
from __future__ import annotations

import logging
import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml
from dotenv import load_dotenv

logger = logging.getLogger(__name__)

DEFAULT_PATH = "config/settings.yaml"
EXAMPLE_PATH = "config/settings.example.yaml"

_ENV_PATTERN = re.compile(r"\$\{([A-Z0-9_]+)\}")
_UNEXPANDED = re.compile(r"^\s*\$\{[A-Z0-9_]+\}\s*$")


def _is_unset(v: Any) -> bool:
    """空字串 / None / 仍是 ${VAR} 樣式（環境變數沒設）視為未設定。"""
    if v is None:
        return True
    if isinstance(v, str):
        s = v.strip()
        return not s or bool(_UNEXPANDED.match(s))
    return False


def _expand_env(value: Any) -> Any:
    """遞迴展開 ${VAR} 為環境變數值；找不到時保留原字串。"""
    if isinstance(value, str):
        def repl(m: re.Match[str]) -> str:
            return os.environ.get(m.group(1), m.group(0))
        return _ENV_PATTERN.sub(repl, value)
    if isinstance(value, dict):
        return {k: _expand_env(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_expand_env(v) for v in value]
    return value


@dataclass
class MoEnvSettings:
    api_key: str = ""
    base_url: str = "https://data.moenv.gov.tw/api/v2"
    page_size: int = 1000
    timeout: float = 30.0
    max_retries: int = 3


@dataclass
class TelegramSettings:
    bot_token: str = ""
    chat_ids: dict[str, str] = field(default_factory=dict)
    default_chat_id: str = ""  # 個人用：daily/alert/admin 沒填時 fallback


@dataclass
class StationAlertThresholds:
    """站層級閾值。單位對齊環境部 aqx_p_432：SO2/NO2/O3 用 ppb、CO 用 ppm、PM 用 μg/m³。"""

    aqi: float = 150
    pm25: float = 35.5    # μg/m³，PM2.5 24h 標準
    so2: float = 75       # ppb（環境部欄位即 ppb，1 hr 標準 75）
    no2: float = 100      # ppb（1 hr 標準 100）
    co: float = 9         # ppm（8 hr 標準 9）
    o3: float = 100       # ppb（8 hr 標準 70；1 hr 寬鬆設 100 觸發）


@dataclass
class RegionAlertThresholds:
    aqi: float = 150
    ratio: float = 0.3


@dataclass
class AirQualityAlertSettings:
    station: StationAlertThresholds = field(default_factory=StationAlertThresholds)
    region: RegionAlertThresholds = field(default_factory=RegionAlertThresholds)


@dataclass
class DailyReportSettings:
    hour: int = 8
    minute: int = 0
    timezone: str = "Asia/Taipei"


@dataclass
class PlantSettings:
    """單一電廠監看設定。"""

    name: str
    counties: list[str] = field(default_factory=list)
    stations: list[str] = field(default_factory=list)


@dataclass
class Settings:
    moenv: MoEnvSettings = field(default_factory=MoEnvSettings)
    databases: dict[str, str] = field(default_factory=dict)
    telegram: TelegramSettings = field(default_factory=TelegramSettings)
    air_quality_alerts: AirQualityAlertSettings = field(
        default_factory=AirQualityAlertSettings
    )
    daily_report: DailyReportSettings = field(default_factory=DailyReportSettings)
    plants: list[PlantSettings] = field(default_factory=list)

    def station_to_plant(self) -> dict[str, str]:
        """逆查表：周界站名 → 電廠名（重複以第一筆為準）。"""
        out: dict[str, str] = {}
        for p in self.plants:
            for s in p.stations:
                out.setdefault(s, p.name)
        return out


def _build_settings(raw: dict[str, Any]) -> Settings:
    moenv = MoEnvSettings(**(raw.get("moenv") or {}))
    databases = raw.get("databases") or {}
    tg_raw = raw.get("telegram") or {}

    bot_token_raw = tg_raw.get("bot_token", "")
    bot_token = "" if _is_unset(bot_token_raw) else str(bot_token_raw).strip()

    default_chat_raw = tg_raw.get("chat_id", "")
    default_chat_id = (
        "" if _is_unset(default_chat_raw) else str(default_chat_raw).strip()
    )

    chat_ids: dict[str, str] = {}
    for k, v in (tg_raw.get("chat_ids") or {}).items():
        if not _is_unset(v):
            chat_ids[k] = str(v).strip()

    # fallback：若 daily/alert/admin 任一未設且有 default_chat_id，自動補上
    if default_chat_id:
        for target in ("daily", "alert", "admin"):
            chat_ids.setdefault(target, default_chat_id)

    telegram = TelegramSettings(
        bot_token=bot_token,
        chat_ids=chat_ids,
        default_chat_id=default_chat_id,
    )
    aq_raw = raw.get("air_quality_alerts") or {}
    air_alerts = AirQualityAlertSettings(
        station=StationAlertThresholds(**(aq_raw.get("station") or {})),
        region=RegionAlertThresholds(**(aq_raw.get("region") or {})),
    )
    daily = DailyReportSettings(**(raw.get("daily_report") or {}))

    plants_raw = raw.get("plants") or {}
    plants: list[PlantSettings] = []
    if isinstance(plants_raw, dict):
        for name, body in plants_raw.items():
            body = body or {}
            plants.append(
                PlantSettings(
                    name=str(name),
                    counties=list(body.get("counties") or []),
                    stations=list(body.get("stations") or []),
                )
            )
    elif isinstance(plants_raw, list):
        # 容忍 list 寫法：每筆要含 name
        for body in plants_raw:
            body = body or {}
            n = body.get("name")
            if not n:
                continue
            plants.append(
                PlantSettings(
                    name=str(n),
                    counties=list(body.get("counties") or []),
                    stations=list(body.get("stations") or []),
                )
            )

    return Settings(
        moenv=moenv,
        databases=databases,
        telegram=telegram,
        air_quality_alerts=air_alerts,
        daily_report=daily,
        plants=plants,
    )


def load_settings(path: str | Path | None = None) -> Settings:
    """載入 settings.yaml + .env。
    優先順序：傳入 path > config/settings.yaml > config/settings.example.yaml。
    """
    load_dotenv(override=False)

    candidate = Path(path) if path else Path(DEFAULT_PATH)
    if not candidate.exists():
        fallback = Path(EXAMPLE_PATH)
        if fallback.exists():
            logger.warning(
                "settings.yaml 不存在，改用範例 %s（請先 cp 並填值）", fallback
            )
            candidate = fallback
        else:
            raise FileNotFoundError(f"找不到設定檔：{candidate} 與 {fallback}")

    with candidate.open("r", encoding="utf-8") as f:
        raw = yaml.safe_load(f) or {}
    raw = _expand_env(raw)
    return _build_settings(raw)
