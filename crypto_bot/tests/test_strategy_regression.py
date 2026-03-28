from __future__ import annotations

from pathlib import Path

import pytest

from strategy import strategy_engine as se
from utils.state_io import write_json_file


def _base_cfg() -> dict:
    return {
        "min_trades": 3,
        "market_regime": {
            "preferred_buy_zone": [0.05, 0.30],
            "min_z_score": -1.5,
            "blocked_regimes": ["unknown"],
        },
        "volatility_filters": {"min_atr": 0.0003, "min_atr_pct": 0.0003},
        "profit_locks": {
            "first_activation": 0.02,
            "initial_lock": 0.01,
            "levels": [[0.04, 0.03], [0.05, 0.04], [0.06, 0.05], [0.08, 0.06]],
            "trailing_activation": 0.10,
            "trailing_gap": 0.02,
            "reset_below_activation": True,
            "max_negative_z_score": -3.5,
        },
    }


def _snapshot(**overrides) -> dict:
    base = {
        "symbol": "TEST-USD",
        "price": 0.12,
        "momentum_norm": 0.0,
        "trade_count": 20,
        "high_24h": 0.20,
        "low_24h": 0.10,
        "atr": 0.01,
        "vwap": 0.14,
        "rsi": 20.0,
        "spread_bps": 20.0,
        "recent_prices": [0.14, 0.135, 0.13, 0.125, 0.12, 0.118, 0.117, 0.116],
        "data_quality_ok": True,
        "data_quality_reason": "ok",
    }
    base.update(overrides)
    return base


@pytest.fixture(autouse=True)
def reset_strategy_globals(monkeypatch, tmp_path: Path):
    for mapping_name in (
        "_last_signal",
        "_last_sell_price",
        "_entry_price",
        "_entry_time",
        "_profit_lock",
        "_peak_pnl",
        "_last_momentum",
        "_last_regime",
        "_last_score",
        "_last_volatility",
        "_last_configured_regime",
        "_last_detected_regime",
        "_last_detected_regime_confidence",
        "_last_detected_regime_confidence_label",
        "_last_detected_regime_stability",
        "_last_detected_regime_persistence",
        "_last_regime_data_quality_status",
        "_last_regime_key_windows_supported",
        "_last_suggested_regime_v2",
        "_last_detection_source",
        "_last_detection_timestamp_epoch",
        "_last_effective_strategy",
        "_last_effective_route",
        "_last_route_eval_ts",
        "_last_regime_eval_ts",
        "_last_auto_fallback_reason",
        "_last_fallback_reason",
        "_last_route_readiness_state",
        "_last_route_timestamp_age_seconds",
        "_last_route_timestamp_fresh",
        "_last_shadow_continuity_state",
        "_last_shadow_age_seconds",
        "_last_failed_gates",
        "_last_decision_diagnostics",
        "_last_buy_block_reason",
        "_last_buy_block_route",
        "_buy_block_counts_by_symbol",
        "_buy_block_counts_by_symbol_route",
        "_pending_entry_contract",
        "_entry_route",
        "_entry_regime",
        "_exit_policy",
        "_entry_confidence",
        "_entry_timestamp",
        "_entry_route_eval_ts",
        "_entry_regime_eval_ts",
        "_shadow_regime_state",
    ):
        getattr(se, mapping_name).clear()

    state_dir = tmp_path / "state"
    state_dir.mkdir(parents=True, exist_ok=True)
    write_json_file(state_dir / "trades.json", [])
    write_json_file(state_dir / "config.json", {})
    write_json_file(state_dir / "strategy_state.json", {})
    write_json_file(state_dir / "paper_state.json", {"positions": {}, "balance": 10000})

    monkeypatch.setattr(se, "STATE_DIR", state_dir)
    monkeypatch.setattr(se, "STRATEGY_STATE_FILE", state_dir / "strategy_state.json")
    monkeypatch.setattr(se, "PAPER_STATE_FILE", state_dir / "paper_state.json")
    monkeypatch.setattr(se, "_synced", True)
    monkeypatch.setattr(se, "_last_paper_state_mtime", None)
    monkeypatch.setattr(se, "_metrics_dirty", False)
    monkeypatch.setattr(se, "_last_metrics_flush_at", 0.0)


def test_mean_reversion_buy_regression():
    decision = se.generate_decision(_snapshot(), _base_cfg())
    assert decision["action"] == "BUY"
    assert decision["reason"] == "bear_market_mean_reversion_buy"


def test_mean_reversion_hold_when_above_buy_zone():
    decision = se.generate_decision(
        _snapshot(
            price=0.16,
            vwap=0.17,
            rsi=55.0,
            recent_prices=[0.14, 0.145, 0.15, 0.155, 0.16, 0.162, 0.164, 0.166],
        ),
        _base_cfg(),
    )
    assert decision["action"] == "HOLD"
    assert decision["reason"] == "price_above_buy_zone"


def test_profit_lock_exit_regression():
    cfg = _base_cfg()
    se.confirm_entry("TEST-USD", 100.0)

    hold_decision = se.generate_decision(
        _snapshot(
            symbol="TEST-USD",
            price=104.0,
            high_24h=110.0,
            low_24h=90.0,
            atr=1.0,
            vwap=102.0,
            rsi=40.0,
            recent_prices=[98.0, 99.0, 100.0, 101.0, 102.0, 103.0, 104.0],
        ),
        cfg,
    )
    assert hold_decision["action"] == "HOLD"
    assert hold_decision["reason"] == "in_position"

    sell_decision = se.generate_decision(
        _snapshot(
            symbol="TEST-USD",
            price=102.0,
            high_24h=110.0,
            low_24h=90.0,
            atr=1.0,
            vwap=101.0,
            rsi=45.0,
            recent_prices=[99.0, 100.0, 101.0, 102.0, 103.0, 102.5, 102.0],
        ),
        cfg,
    )
    assert sell_decision["action"] == "SELL"
    assert str(sell_decision["reason"]).startswith("profit_lock_exit_")


def test_invalid_entry_price_is_guarded_in_sell_path():
    cfg = _base_cfg()
    se._entry_price["TEST-USD"] = 0.0
    se._entry_time["TEST-USD"] = 1000.0
    se._last_signal["TEST-USD"] = "BUY"

    decision = se.generate_decision(
        _snapshot(
            symbol="TEST-USD",
            price=99.0,
            high_24h=110.0,
            low_24h=90.0,
            atr=1.0,
            vwap=100.0,
        ),
        cfg,
    )
    assert decision["action"] == "HOLD"
    assert decision["reason"] == "invalid_entry_price"


def test_buy_block_counters_increment_by_symbol_and_route():
    cfg = _base_cfg()
    decision = se.generate_decision(
        _snapshot(
            trade_count=0,
            atr=0.0,
            vwap=None,
        ),
        cfg,
    )
    assert decision["action"] == "HOLD"
    assert decision["reason"] == "insufficient_data"

    symbol_counts = se._buy_block_counts_by_symbol.get("TEST-USD", {})
    assert symbol_counts.get("insufficient_data", 0) >= 1

    by_symbol_route = se._buy_block_counts_by_symbol_route.get("TEST-USD", {})
    assert "mean_reversion" in by_symbol_route
    assert by_symbol_route["mean_reversion"].get("insufficient_data", 0) >= 1
    assert se._last_buy_block_reason.get("TEST-USD") == "insufficient_data"
    assert se._last_buy_block_route.get("TEST-USD") == "mean_reversion"


def test_auto_with_scalper_override_forces_scalper_route():
    cfg = _base_cfg()
    cfg["symbol_strategies"] = {"GST-USD": "volatility_scalper"}
    cfg["volatility_scalper"] = {"symbols": ["GST-USD"]}
    cfg["token_regimes"] = {"GST-USD": "AUTO"}

    decision = se.generate_decision(
        _snapshot(
            symbol="GST-USD",
            price=1.005,
            vwap=1.02,
            atr=0.02,
            momentum_norm=0.5,
            high_24h=1.30,
            low_24h=0.80,
            spread_bps=20.0,
            rsi=50.0,
            recent_prices=[0.98, 0.99, 1.0, 1.01, 1.015, 1.01, 1.005],
        ),
        cfg,
    )

    assert decision["effective_strategy"] == "volatility_scalper"
    assert decision["effective_route"] == "volatility_scalper"
    assert decision.get("fallback_reason") == "manual_scalper_override"
    assert str(decision["reason"]).startswith("volatility_scalper_")


def test_shadow_regime_telemetry_is_additive_only():
    decision = se.generate_decision(_snapshot(), _base_cfg())

    assert decision["action"] == "BUY"
    assert decision["reason"] == "bear_market_mean_reversion_buy"

    shadow = se._shadow_regime_state.get("TEST-USD")
    assert shadow is not None
    assert shadow["candidate_regime"] in {
        "accumulation",
        "range",
        "chop",
        "trend_up",
        "trend_down",
        "dump",
        "spike",
        "unknown",
    }
    assert shadow["stable_regime"] in {
        "accumulation",
        "range",
        "chop",
        "trend_up",
        "trend_down",
        "dump",
        "spike",
        "unknown",
    }
    assert 0.0 <= float(shadow["confidence"]) <= 0.99
