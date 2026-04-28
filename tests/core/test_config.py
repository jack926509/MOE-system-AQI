import os
import tempfile
from pathlib import Path

import pytest

from core.config import _build_settings, _expand_env, _is_unset, load_settings


def _yaml_to_settings(yaml_text: str):
    import yaml
    raw = yaml.safe_load(yaml_text) or {}
    raw = _expand_env(raw)
    return _build_settings(raw)


def test_is_unset_variants():
    assert _is_unset(None)
    assert _is_unset("")
    assert _is_unset("   ")
    assert _is_unset("${TELEGRAM_CHAT_ID}")  # 未展開
    assert _is_unset("  ${FOO}  ")
    assert not _is_unset("123456789")
    assert not _is_unset("-1001234")


def test_chat_id_fallback_fills_missing(monkeypatch):
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "tok")
    monkeypatch.setenv("TELEGRAM_CHAT_ID", "555")
    monkeypatch.delenv("TELEGRAM_CHAT_ID_DAILY", raising=False)
    monkeypatch.delenv("TELEGRAM_CHAT_ID_ALERT", raising=False)
    monkeypatch.delenv("TELEGRAM_CHAT_ID_ADMIN", raising=False)

    settings = _yaml_to_settings("""
telegram:
  bot_token: ${TELEGRAM_BOT_TOKEN}
  chat_id: ${TELEGRAM_CHAT_ID}
  chat_ids:
    daily: ${TELEGRAM_CHAT_ID_DAILY}
    alert: ${TELEGRAM_CHAT_ID_ALERT}
    admin: ${TELEGRAM_CHAT_ID_ADMIN}
""")
    assert settings.telegram.bot_token == "tok"
    assert settings.telegram.default_chat_id == "555"
    assert settings.telegram.chat_ids["daily"] == "555"
    assert settings.telegram.chat_ids["alert"] == "555"
    assert settings.telegram.chat_ids["admin"] == "555"


def test_chat_id_specific_overrides_default(monkeypatch):
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "tok")
    monkeypatch.setenv("TELEGRAM_CHAT_ID", "555")
    monkeypatch.setenv("TELEGRAM_CHAT_ID_ALERT", "999")
    monkeypatch.delenv("TELEGRAM_CHAT_ID_DAILY", raising=False)
    monkeypatch.delenv("TELEGRAM_CHAT_ID_ADMIN", raising=False)

    settings = _yaml_to_settings("""
telegram:
  bot_token: ${TELEGRAM_BOT_TOKEN}
  chat_id: ${TELEGRAM_CHAT_ID}
  chat_ids:
    daily: ${TELEGRAM_CHAT_ID_DAILY}
    alert: ${TELEGRAM_CHAT_ID_ALERT}
    admin: ${TELEGRAM_CHAT_ID_ADMIN}
""")
    assert settings.telegram.chat_ids["alert"] == "999"      # specific 勝出
    assert settings.telegram.chat_ids["daily"] == "555"      # fallback
    assert settings.telegram.chat_ids["admin"] == "555"      # fallback


def test_no_default_no_fallback(monkeypatch):
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "tok")
    monkeypatch.delenv("TELEGRAM_CHAT_ID", raising=False)
    monkeypatch.delenv("TELEGRAM_CHAT_ID_DAILY", raising=False)
    monkeypatch.delenv("TELEGRAM_CHAT_ID_ALERT", raising=False)
    monkeypatch.delenv("TELEGRAM_CHAT_ID_ADMIN", raising=False)

    settings = _yaml_to_settings("""
telegram:
  bot_token: ${TELEGRAM_BOT_TOKEN}
  chat_id: ${TELEGRAM_CHAT_ID}
  chat_ids:
    daily: ${TELEGRAM_CHAT_ID_DAILY}
""")
    assert settings.telegram.default_chat_id == ""
    assert settings.telegram.chat_ids == {}


def test_load_settings_uses_env(monkeypatch):
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "tok")
    monkeypatch.setenv("TELEGRAM_CHAT_ID", "42")
    monkeypatch.setenv("MOENV_API_KEY", "k")
    with tempfile.TemporaryDirectory() as d:
        path = Path(d) / "s.yaml"
        path.write_text("""
moenv:
  api_key: ${MOENV_API_KEY}
telegram:
  bot_token: ${TELEGRAM_BOT_TOKEN}
  chat_id: ${TELEGRAM_CHAT_ID}
""", encoding="utf-8")
        settings = load_settings(path)
        assert settings.telegram.bot_token == "tok"
        assert settings.telegram.chat_ids["daily"] == "42"
        assert settings.telegram.chat_ids["alert"] == "42"
        assert settings.telegram.chat_ids["admin"] == "42"
