from __future__ import annotations

from pathlib import Path

import pytest

from utils import config_loader
from utils.config_schema import CONFIG_SCHEMA_VERSION, normalize_config
from utils.state_io import read_json_file, write_json_file


def test_normalize_config_warn_mode_populates_defaults():
    raw = {
        "enabled": True,
        "symbols": ["btc-usd", "", 1, "btc-usd", "eth-usd"],
        "risk": {
            "max_concurrent_trades": "3",
            "trade_window_utc": {"enabled": "yes", "start_hour_utc": 30, "end_hour_utc": -1},
        },
    }

    normalized, warnings, changed = normalize_config(raw, strict=False)

    assert changed is True
    assert warnings
    assert normalized["config_version"] == CONFIG_SCHEMA_VERSION
    assert normalized["symbols"] == ["BTC-USD", "ETH-USD"]
    assert normalized["risk"]["max_concurrent_trades"] == 3
    assert normalized["risk"]["trade_window_utc"]["enabled"] is True
    assert normalized["risk"]["trade_window_utc"]["start_hour_utc"] == 23
    assert normalized["risk"]["trade_window_utc"]["end_hour_utc"] == 0
    assert normalized["risk"]["stale_losing_review_age_hours"] == 36.0
    assert normalized["risk"]["stale_losing_review_unrealized_pnl_pct"] == -10.0


def test_normalize_config_stale_losing_review_thresholds_are_clamped():
    raw = {
        "enabled": True,
        "symbols": ["btc-usd"],
        "risk": {
            "stale_losing_review_age_hours": -5,
            "stale_losing_review_unrealized_pnl_pct": 4,
        },
    }

    normalized, warnings, changed = normalize_config(raw, strict=False)

    assert changed is True
    assert warnings
    assert normalized["risk"]["stale_losing_review_age_hours"] == 0.0
    assert normalized["risk"]["stale_losing_review_unrealized_pnl_pct"] == 0.0


def test_normalize_config_strict_mode_raises_on_warnings():
    with pytest.raises(ValueError):
        normalize_config({}, strict=True)


def test_normalize_config_token_regimes_accepts_valid_values():
    raw = {
        "enabled": True,
        "symbols": ["btc-usd"],
        "token_regimes": {
            "btc-usd": "mean_reversion",
            "eth-usd": "TREND_PULLBACK",
        },
    }

    normalized, warnings, changed = normalize_config(raw, strict=False)
    assert changed is True
    assert normalized["token_regimes"]["BTC-USD"] == "MEAN_REVERSION"
    assert normalized["token_regimes"]["ETH-USD"] == "TREND_PULLBACK"
    assert warnings


def test_normalize_config_token_regimes_rejects_invalid_in_strict_mode():
    raw = {
        "enabled": True,
        "symbols": ["btc-usd"],
        "token_regimes": {
            "btc-usd": "UNKNOWN_MODE",
        },
    }
    with pytest.raises(ValueError) as exc:
        normalize_config(raw, strict=True)
    assert "token_regimes.BTC-USD invalid" in str(exc.value)


def test_load_config_warn_mode_does_not_autosave_by_default(tmp_path: Path, monkeypatch):
    cfg_path = tmp_path / "config.json"
    write_json_file(cfg_path, {"enabled": True, "symbols": ["btc-usd"]})

    monkeypatch.setattr(config_loader, "CONFIG_PATH", cfg_path)
    monkeypatch.setattr(config_loader, "_AUTOSAVE_CONFIG_NORMALIZATION", False)
    monkeypatch.setattr(config_loader, "_STRICT_CONFIG_VALIDATION", False)
    monkeypatch.setattr(config_loader, "_last_warning_fingerprint", None)

    loaded = config_loader.load_config()
    on_disk = read_json_file(cfg_path, strict=True)

    assert loaded["config_version"] == CONFIG_SCHEMA_VERSION
    assert "config_version" not in on_disk


def test_update_config_writes_normalized_payload(tmp_path: Path, monkeypatch):
    cfg_path = tmp_path / "config.json"
    write_json_file(cfg_path, {"enabled": True, "symbols": ["btc-usd"]})

    monkeypatch.setattr(config_loader, "CONFIG_PATH", cfg_path)
    monkeypatch.setattr(config_loader, "_STRICT_CONFIG_VALIDATION", False)
    monkeypatch.setattr(config_loader, "_last_warning_fingerprint", None)

    config_loader.update_config(
        lambda current: {
            **current,
            "symbols": ["ada-usd", "eth-usd", "eth-usd"],
            "risk": {"max_concurrent_trades": "7"},
        }
    )

    updated = read_json_file(cfg_path, strict=True)
    assert updated["symbols"] == ["ADA-USD", "ETH-USD"]
    assert updated["risk"]["max_concurrent_trades"] == 7
    assert updated["config_version"] == CONFIG_SCHEMA_VERSION
