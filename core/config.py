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


@dataclass
class StationAlertThresholds:
    aqi: float = 150
    pm25: float = 35.5
    so2: float = 0.075
    no2: float = 0.1


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
class Settings:
    moenv: MoEnvSettings = field(default_factory=MoEnvSettings)
    databases: dict[str, str] = field(default_factory=dict)
    telegram: TelegramSettings = field(default_factory=TelegramSettings)
    air_quality_alerts: AirQualityAlertSettings = field(
        default_factory=AirQualityAlertSettings
    )
    daily_report: DailyReportSettings = field(default_factory=DailyReportSettings)


def _build_settings(raw: dict[str, Any]) -> Settings:
    moenv = MoEnvSettings(**(raw.get("moenv") or {}))
    databases = raw.get("databases") or {}
    tg_raw = raw.get("telegram") or {}
    telegram = TelegramSettings(
        bot_token=tg_raw.get("bot_token", ""),
        chat_ids={k: str(v) for k, v in (tg_raw.get("chat_ids") or {}).items() if v},
    )
    aq_raw = raw.get("air_quality_alerts") or {}
    air_alerts = AirQualityAlertSettings(
        station=StationAlertThresholds(**(aq_raw.get("station") or {})),
        region=RegionAlertThresholds(**(aq_raw.get("region") or {})),
    )
    daily = DailyReportSettings(**(raw.get("daily_report") or {}))
    return Settings(
        moenv=moenv,
        databases=databases,
        telegram=telegram,
        air_quality_alerts=air_alerts,
        daily_report=daily,
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
