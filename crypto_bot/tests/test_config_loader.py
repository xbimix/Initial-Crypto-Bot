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
    assert normalized["trading_enabled"] is False
    assert normalized["symbols"] == ["BTC-USD", "ETH-USD"]
    assert normalized["risk"]["max_concurrent_trades"] == 3
    assert normalized["risk"]["trade_window_utc"]["enabled"] is True
    assert normalized["risk"]["trade_window_utc"]["start_hour_utc"] == 23
    assert normalized["risk"]["trade_window_utc"]["end_hour_utc"] == 0
    assert normalized["risk"]["stale_losing_review_age_hours"] == 36.0
    assert normalized["risk"]["stale_losing_review_unrealized_pnl_pct"] == -10.0
    assert normalized["market_data"]["source_map"]["candles"]["authoritative"] == "official_signed"
    assert normalized["market_data"]["source_map"]["candles"]["allow_public_fallback"] is False
    assert normalized["market_data"]["source_map"]["orderbook"]["allow_public_fallback"] is True
    assert normalized["market_data"]["freshness_slo"]["min_fresh_1h"] == 1
    assert normalized["market_data"]["freshness_slo"]["min_fresh_4h"] == 1
    assert normalized["market_data"]["freshness_slo"]["min_fresh_24h"] == 0


def test_normalize_config_source_map_invalid_values_are_normalized():
    raw = {
        "enabled": True,
        "symbols": ["btc-usd"],
        "market_data": {
            "source_map": {
                "candles": {
                    "authoritative": "invalid",
                    "allow_public_fallback": "yes",
                    "allow_snapshot_fallback": "nope",
                },
                "orderbook": {
                    "allow_public_fallback": "off",
                },
            },
            "freshness_slo": {
                "min_fresh_1h": -5,
                "max_sync_errors": "2",
            },
        },
    }

    normalized, warnings, changed = normalize_config(raw, strict=False)
    assert changed is True
    assert warnings
    assert normalized["market_data"]["source_map"]["candles"]["authoritative"] == "official_signed"
    assert normalized["market_data"]["source_map"]["candles"]["allow_public_fallback"] is True
    assert normalized["market_data"]["source_map"]["candles"]["allow_snapshot_fallback"] is False
    assert normalized["market_data"]["source_map"]["orderbook"]["allow_public_fallback"] is False
    assert normalized["market_data"]["freshness_slo"]["min_fresh_1h"] == 0
    assert normalized["market_data"]["freshness_slo"]["max_sync_errors"] == 2


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


def test_load_config_falls_back_to_legacy_path_when_runtime_missing(tmp_path: Path, monkeypatch):
    runtime_cfg = tmp_path / "runtime" / "state" / "config.json"
    legacy_cfg = tmp_path / "legacy" / "state" / "config.json"
    write_json_file(legacy_cfg, {"enabled": True, "symbols": ["btc-usd"]})

    monkeypatch.setattr(config_loader, "CONFIG_PATH", runtime_cfg)
    monkeypatch.setattr(config_loader, "LEGACY_CONFIG_PATH", legacy_cfg)
    monkeypatch.setattr(config_loader, "_AUTOSAVE_CONFIG_NORMALIZATION", False)
    monkeypatch.setattr(config_loader, "_STRICT_CONFIG_VALIDATION", False)
    monkeypatch.setattr(config_loader, "_last_warning_fingerprint", None)

    loaded = config_loader.load_config()
    assert loaded["enabled"] is True
    assert loaded["symbols"] == ["BTC-USD"]


def test_update_config_seeds_runtime_file_from_legacy(tmp_path: Path, monkeypatch):
    runtime_cfg = tmp_path / "runtime" / "state" / "config.json"
    legacy_cfg = tmp_path / "legacy" / "state" / "config.json"
    write_json_file(legacy_cfg, {"enabled": True, "symbols": ["btc-usd"]})

    monkeypatch.setattr(config_loader, "CONFIG_PATH", runtime_cfg)
    monkeypatch.setattr(config_loader, "LEGACY_CONFIG_PATH", legacy_cfg)
    monkeypatch.setattr(config_loader, "_STRICT_CONFIG_VALIDATION", False)
    monkeypatch.setattr(config_loader, "_last_warning_fingerprint", None)

    config_loader.update_config(lambda current: {**current, "symbols": ["eth-usd"]})
    assert runtime_cfg.exists()
    updated = read_json_file(runtime_cfg, strict=True)
    assert updated["enabled"] is True
    assert updated["symbols"] == ["ETH-USD"]


def test_load_config_fails_fast_on_invalid_sizing_mode(tmp_path: Path, monkeypatch):
    cfg_path = tmp_path / "config.json"
    write_json_file(
        cfg_path,
        {"enabled": True, "symbols": ["btc-usd"], "risk": {"sizing_mode": "totally_wrong"}},
    )
    monkeypatch.setattr(config_loader, "CONFIG_PATH", cfg_path)
    monkeypatch.setattr(config_loader, "LEGACY_CONFIG_PATH", tmp_path / "legacy_config.json")
    monkeypatch.setattr(config_loader, "_STRICT_CONFIG_VALIDATION", False)
    monkeypatch.setattr(config_loader, "_last_warning_fingerprint", None)

    with pytest.raises(ValueError):
        config_loader.load_config()


def test_load_config_fails_fast_on_negative_execution_fee(tmp_path: Path, monkeypatch):
    cfg_path = tmp_path / "config.json"
    write_json_file(
        cfg_path,
        {"enabled": True, "symbols": ["btc-usd"], "paper_execution": {"taker_fee_bps": -3}},
    )
    monkeypatch.setattr(config_loader, "CONFIG_PATH", cfg_path)
    monkeypatch.setattr(config_loader, "LEGACY_CONFIG_PATH", tmp_path / "legacy_config.json")
    monkeypatch.setattr(config_loader, "_STRICT_CONFIG_VALIDATION", False)
    monkeypatch.setattr(config_loader, "_last_warning_fingerprint", None)

    with pytest.raises(ValueError):
        config_loader.load_config()


def test_normalize_config_tuning_profile_is_normalized_to_lowercase():
    raw = {
        "enabled": True,
        "symbols": ["btc-usd"],
        "strategy_defaults": {
            "tuning_profile": "BALANCED",
        },
    }
    normalized, warnings, changed = normalize_config(raw, strict=False)
    assert changed is True
    assert warnings
    assert normalized["strategy_defaults"]["tuning_profile"] == "balanced"


def test_normalize_config_invalid_tuning_profile_defaults_to_conservative():
    raw = {
        "enabled": True,
        "symbols": ["btc-usd"],
        "strategy_defaults": {
            "tuning_profile": "very_fast",
        },
    }
    normalized, warnings, changed = normalize_config(raw, strict=False)
    assert changed is True
    assert warnings
    assert normalized["strategy_defaults"]["tuning_profile"] == "conservative"


def test_normalize_config_adds_execution_realism_and_stop_sizing_defaults():
    raw = {
        "enabled": True,
        "symbols": ["btc-usd"],
        "risk": {},
    }
    normalized, warnings, changed = normalize_config(raw, strict=False)
    assert changed is True
    assert warnings
    assert normalized["paper_execution"]["enabled"] is False
    assert normalized["paper_execution"]["taker_fee_bps"] == 12.0
    assert normalized["paper_execution"]["maker_fee_bps"] == 2.0
    assert normalized["paper_execution"]["hard_reject_spread_bps"] == 250.0
    assert normalized["paper_execution"]["latency_slippage_bps_per_sec"] == 1.5
    assert normalized["risk"]["stop_atr_mult_default"] == 1.4
    assert normalized["risk"]["stop_atr_mult_trend"] == 2.0
    assert normalized["risk"]["liquidity_hard_spread_bps"] == 220.0
    assert normalized["risk"]["sizing_mode"] == "auto"
    assert normalized["risk"]["min_trade_notional_usd"] == 10.0
