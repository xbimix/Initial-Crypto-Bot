from __future__ import annotations

from pathlib import Path
import time

import pytest

from strategy import strategy_engine as se
from utils.state_io import write_json_file


def _base_cfg() -> dict:
    return {
        "min_trades": 3,
        "market_regime": {
            "preferred_buy_zone": [0.05, 0.30],
            "min_z_score": -1.5,
            "min_score_to_buy": 60,
            "blocked_regimes": [],
            "hard_blocked_regimes": [],
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
        "ema_50": 0.13,
        "ema_200": 0.12,
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
        "_last_ready_for_non_mr_route",
        "_last_non_mr_ready_reason",
        "_last_route_readiness_state",
        "_last_route_timestamp_age_seconds",
        "_last_route_timestamp_fresh",
        "_last_shadow_continuity_state",
        "_last_shadow_age_seconds",
        "_last_failed_gates",
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


def test_auto_and_mean_reversion_default_path_unchanged():
    cfg_auto = _base_cfg()
    cfg_auto["token_regimes"] = {"TEST-USD": "AUTO"}
    auto_decision = se.generate_decision(_snapshot(), cfg_auto)
    assert auto_decision["action"] == "BUY"
    assert auto_decision["reason"] == "bear_market_mean_reversion_buy"

    cfg_manual = _base_cfg()
    cfg_manual["token_regimes"] = {"TEST-USD": "MEAN_REVERSION"}
    manual_decision = se.generate_decision(_snapshot(), cfg_manual)
    assert manual_decision["action"] == "BUY"
    assert manual_decision["reason"] == "bear_market_mean_reversion_buy"


def test_missing_token_regime_defaults_to_mean_reversion():
    decision = se.generate_decision(_snapshot(), _base_cfg())
    assert decision["action"] == "BUY"
    assert decision["reason"] == "bear_market_mean_reversion_buy"
    assert decision["configured_regime"] == "MEAN_REVERSION"


def test_auto_refreshes_stale_shadow_before_route_resolution(monkeypatch):
    cfg = _base_cfg()
    cfg["token_regimes"] = {"TEST-USD": "AUTO"}
    cfg["strategy_defaults"] = {
        "router": {
            "auto_use_current_cycle_shadow": False,
            "auto_max_route_age_seconds": 120,
        }
    }

    # Simulate stale/missing shadow state before this decision cycle.
    se._shadow_regime_state.clear()

    observed: dict[str, float | bool] = {
        "shadow_present_pre_route": False,
        "shadow_age_seconds_pre_route": 999999.0,
    }

    def fake_resolve_entry_route(*, cfg, symbol, snapshot, default_strategy, shadow_state):
        row = shadow_state.get(symbol)
        last_update = float(row.get("last_update_ts", 0.0)) if isinstance(row, dict) else 0.0
        observed["shadow_present_pre_route"] = bool(last_update > 0.0)
        observed["shadow_age_seconds_pre_route"] = max(0.0, time.time() - last_update) if last_update else 999999.0
        return {
            "configured_regime": "AUTO",
            "detected_regime": "MEAN_REVERSION_FRIENDLY",
            "effective_strategy": "mean_reversion",
            "effective_route": "mean_reversion",
            "route_eval_ts": time.time(),
            "regime_eval_ts": time.time(),
            "ready_for_non_mr_route": False,
            "non_mr_ready_reason": "core_timeframe_not_ready:test",
        }

    monkeypatch.setattr(se, "resolve_entry_route", fake_resolve_entry_route)
    monkeypatch.setattr(se, "evaluate_regime_unified", lambda **kwargs: {})
    monkeypatch.setattr(se, "detect_regime", lambda snapshot, regime_cfg: "range")
    monkeypatch.setattr(se, "_evaluate_sell", lambda **kwargs: None)
    monkeypatch.setattr(se, "_evaluate_buy", lambda **kwargs: se._decision("TEST-USD", "HOLD", 0.12, 0.0, "test_hold"))
    monkeypatch.setattr(se, "_compute_buy_diagnostics", lambda **kwargs: ("range", 50.0, 0.5, 0.01))

    decision = se.generate_decision(_snapshot(), cfg)
    assert decision["action"] == "HOLD"
    assert observed["shadow_present_pre_route"] is True
    assert float(observed["shadow_age_seconds_pre_route"]) < 5.0


def test_observe_only_blocks_buys_but_keeps_sell_path():
    cfg = _base_cfg()
    cfg["token_regimes"] = {"TEST-USD": "OBSERVE_ONLY"}

    blocked_buy = se.generate_decision(_snapshot(), cfg)
    assert blocked_buy["action"] == "HOLD"
    assert blocked_buy["reason"] == "observe_only_mode"

    se.confirm_entry("TEST-USD", 100.0)
    hold = se.generate_decision(
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
    assert hold["action"] == "HOLD"

    sell = se.generate_decision(
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
    assert sell["action"] == "SELL"
    assert str(sell["reason"]).startswith("profit_lock_exit_")


def test_manual_trend_pullback_route_triggers_entry():
    cfg = _base_cfg()
    cfg["token_regimes"] = {"TEST-USD": "TREND_PULLBACK"}
    cfg["market_regime"]["min_score_to_buy"] = 0

    decision = se.generate_decision(
        _snapshot(
            price=101.4,
            momentum_norm=0.4,
            trade_count=30,
            high_24h=110.0,
            low_24h=90.0,
            atr=1.0,
            vwap=101.3,
            ema_50=101.2,
            ema_200=95.0,
            ema_50_slope=0.08,
            recent_prices=[96.0, 97.8, 99.2, 100.4, 101.6, 100.8, 101.2, 101.4],
        ),
        cfg,
    )
    assert decision["action"] == "BUY"
    assert decision["reason"] == "trend_pullback_entry"
    assert decision["effective_strategy"] == "trend_pullback"


def test_manual_breakout_momentum_route_triggers_entry():
    cfg = _base_cfg()
    cfg["token_regimes"] = {"TEST-USD": "BREAKOUT_MOMENTUM"}
    cfg["market_regime"]["min_score_to_buy"] = 0

    decision = se.generate_decision(
        _snapshot(
            price=109.9,
            momentum_norm=0.85,
            trade_count=45,
            high_24h=110.0,
            low_24h=100.0,
            atr=1.0,
            vwap=108.0,
            rsi=78.0,
            ema_50=107.5,
            ema_200=104.0,
            recent_prices=[103.0, 104.5, 105.2, 106.3, 107.1, 108.2, 109.0, 109.9],
        ),
        cfg,
    )
    assert decision["action"] == "BUY"
    assert decision["reason"] == "breakout_momentum_entry"
    assert decision["effective_strategy"] == "breakout_momentum"


def test_auto_low_confidence_falls_back_to_default():
    cfg = _base_cfg()
    cfg["token_regimes"] = {"TEST-USD": "AUTO"}
    cfg["strategy_defaults"] = {"router": {"auto_use_multitimeframe_advisory": True}}
    decision = se.generate_decision(
        _snapshot(
            regime_advisory={
                "suggestedRegime": "TREND_CONTINUATION",
                "confidenceScore": 40,
                "dataQuality": {"status": "GOOD", "supportedKeyWindows": True},
            },
        ),
        cfg,
    )
    assert decision["action"] == "BUY"
    assert decision["reason"] == "bear_market_mean_reversion_buy"
    assert decision["effective_strategy"] == "mean_reversion"
    assert decision["auto_fallback_reason"] == "low_confidence"
    assert decision["ready_for_non_mr_route"] is False
    assert decision["non_mr_ready_reason"] == "low_confidence"


def test_auto_low_confidence_falls_back_to_mean_reversion_even_with_strategy_override():
    cfg = _base_cfg()
    cfg["token_regimes"] = {"TEST-USD": "AUTO"}
    cfg["symbol_strategies"] = {"TEST-USD": "trend_pullback"}
    cfg["strategy_defaults"] = {"router": {"auto_use_multitimeframe_advisory": True}}

    decision = se.generate_decision(
        _snapshot(
            regime_advisory={
                "suggestedRegime": "TREND_CONTINUATION",
                "confidenceScore": 35,
                "dataQuality": {"status": "GOOD", "supportedKeyWindows": True},
            },
        ),
        cfg,
    )
    assert decision["action"] == "BUY"
    assert decision["reason"] == "bear_market_mean_reversion_buy"
    assert decision["effective_strategy"] == "mean_reversion"
    assert decision["auto_fallback_reason"] == "low_confidence"


def test_manual_scalper_override_takes_precedence_over_auto_regime():
    cfg = _base_cfg()
    cfg["token_regimes"] = {"TEST-USD": "AUTO"}
    cfg["symbol_strategies"] = {"TEST-USD": "volatility_scalper"}
    cfg["strategy_defaults"] = {"router": {"auto_use_multitimeframe_advisory": True}}

    decision = se.generate_decision(
        _snapshot(
            momentum_norm=0.7,
            trade_count=60,
            atr=0.03,
            regime_advisory={
                "suggestedRegime": "TREND_CONTINUATION",
                "confidenceScore": 90,
                "stabilityScore": 85,
                "persistenceScore": 84,
                "dataQuality": {"status": "GOOD", "supportedKeyWindows": True},
            },
        ),
        cfg,
    )
    assert decision["configured_regime"] == "AUTO"
    assert decision["effective_strategy"] == "volatility_scalper"
    assert decision["effective_route"] == "volatility_scalper"
    assert decision["fallback_reason"] == "manual_scalper_override"


def test_scalper_symbol_membership_alone_does_not_force_scalper_route():
    cfg = _base_cfg()
    cfg["token_regimes"] = {"TEST-USD": "AUTO"}
    cfg["volatility_scalper"] = {"enabled": True, "symbols": ["TEST-USD"]}
    cfg["strategy_defaults"] = {
        "router": {
            "auto_use_multitimeframe_advisory": True,
            "auto_use_route_quality_gates": False,
        }
    }

    decision = se.generate_decision(
        _snapshot(
            price=101.4,
            momentum_norm=0.42,
            trade_count=30,
            high_24h=110.0,
            low_24h=90.0,
            atr=1.0,
            vwap=101.3,
            ema_50=101.2,
            ema_200=95.0,
            ema_50_slope=0.08,
            recent_prices=[96.0, 97.8, 99.2, 100.4, 101.6, 100.8, 101.2, 101.4],
            regime_advisory={
                "suggestedRegime": "TREND_CONTINUATION",
                "confidenceScore": 82,
                "stabilityScore": 79,
                "persistenceScore": 78,
                "dataQuality": {"status": "GOOD", "supportedKeyWindows": True},
            },
        ),
        cfg,
    )
    assert decision["effective_strategy"] == "trend_pullback"
    assert decision["effective_route"] == "trend_pullback"
    assert decision.get("fallback_reason") != "manual_scalper_override"


def test_auto_high_confidence_routes_to_trend_pullback():
    cfg = _base_cfg()
    cfg["token_regimes"] = {"TEST-USD": "AUTO"}
    cfg["market_regime"]["min_score_to_buy"] = 0
    cfg["strategy_defaults"] = {
        "router": {
            "auto_use_multitimeframe_advisory": True,
            "auto_use_route_quality_gates": False,
        }
    }

    decision = se.generate_decision(
        _snapshot(
            price=101.4,
            momentum_norm=0.42,
            trade_count=30,
            high_24h=110.0,
            low_24h=90.0,
            atr=1.0,
            vwap=101.3,
            ema_50=101.2,
            ema_200=95.0,
            ema_50_slope=0.08,
            recent_prices=[96.0, 97.8, 99.2, 100.4, 101.6, 100.8, 101.2, 101.4],
            regime_advisory={
                "suggestedRegime": "TREND_CONTINUATION",
                "confidenceScore": 82,
                "stabilityScore": 79,
                "persistenceScore": 78,
                "dataQuality": {"status": "GOOD", "supportedKeyWindows": True},
            },
        ),
        cfg,
    )
    assert decision["action"] == "BUY"
    assert decision["reason"] == "trend_pullback_entry"
    assert decision["effective_strategy"] == "trend_pullback"
    assert decision["ready_for_non_mr_route"] is True
    assert decision["non_mr_ready_reason"] == "auto_quality_gates_passed"


def test_auto_uses_shadow_high_confidence_when_snapshot_advisory_missing():
    cfg = _base_cfg()
    cfg["token_regimes"] = {"TEST-USD": "AUTO"}
    cfg["market_regime"]["min_score_to_buy"] = 0
    cfg["strategy_defaults"] = {
        "router": {
            "auto_min_confirmations": 2,
            "auto_use_route_quality_gates": False,
        }
    }

    se._shadow_regime_state["TEST-USD"] = {
        "candidate_regime": "trend_up",
        "stable_regime": "trend_up",
        "confirmations": 3,
        "confidence": 0.92,
        "last_update_ts": se.time.time(),
        "last_switch_ts": se.time.time(),
        "switched": False,
    }

    decision = se.generate_decision(
        _snapshot(
            price=101.4,
            momentum_norm=0.42,
            trade_count=30,
            high_24h=110.0,
            low_24h=90.0,
            atr=1.0,
            vwap=101.3,
            ema_50=101.2,
            ema_200=95.0,
            ema_50_slope=0.08,
            recent_prices=[96.0, 97.8, 99.2, 100.4, 101.6, 100.8, 101.2, 101.4],
        ),
        cfg,
    )
    assert decision["configured_regime"] == "AUTO"
    assert decision["action"] == "BUY"
    assert decision["reason"] == "trend_pullback_entry"
    assert decision["effective_strategy"] == "trend_pullback"


def test_auto_shadow_mixed_or_unclear_falls_back_to_mean_reversion():
    cfg = _base_cfg()
    cfg["token_regimes"] = {"TEST-USD": "AUTO"}
    cfg["strategy_defaults"] = {"router": {"auto_min_confirmations": 2}}

    se._shadow_regime_state["TEST-USD"] = {
        "candidate_regime": "chop",
        "stable_regime": "chop",
        "confirmations": 4,
        "confidence": 0.95,
        "last_update_ts": se.time.time(),
        "last_switch_ts": se.time.time(),
        "switched": False,
    }

    decision = se.generate_decision(_snapshot(), cfg)
    assert decision["configured_regime"] == "AUTO"
    assert decision["effective_strategy"] == "mean_reversion"
    assert decision["reason"] == "bear_market_mean_reversion_buy"
    assert decision["auto_fallback_reason"] == "mixed_or_unclear_regime"


def test_auto_high_confidence_routes_to_breakout_momentum():
    cfg = _base_cfg()
    cfg["token_regimes"] = {"TEST-USD": "AUTO"}
    cfg["market_regime"]["min_score_to_buy"] = 0
    cfg["strategy_defaults"] = {
        "router": {
            "auto_use_multitimeframe_advisory": True,
            "auto_use_route_quality_gates": False,
        }
    }

    decision = se.generate_decision(
        _snapshot(
            price=109.9,
            momentum_norm=0.9,
            trade_count=45,
            high_24h=110.0,
            low_24h=100.0,
            atr=1.0,
            vwap=108.0,
            rsi=78.0,
            ema_50=107.5,
            ema_200=104.0,
            recent_prices=[103.0, 104.5, 105.2, 106.3, 107.1, 108.2, 109.0, 109.9],
            regime_advisory={
                "suggestedRegime": "BREAKOUT_EXPANSION",
                "confidenceScore": 84,
                "stabilityScore": 81,
                "persistenceScore": 80,
                "dataQuality": {"status": "GOOD", "supportedKeyWindows": True},
            },
        ),
        cfg,
    )
    assert decision["action"] == "BUY"
    assert decision["reason"] == "breakout_momentum_entry"
    assert decision["effective_strategy"] == "breakout_momentum"


def test_auto_trend_route_blocked_when_not_promoted():
    cfg = _base_cfg()
    cfg["token_regimes"] = {"TEST-USD": "AUTO"}
    cfg["strategy_defaults"] = {"router": {"auto_use_multitimeframe_advisory": True}}

    decision = se.generate_decision(
        _snapshot(
            price=101.4,
            momentum_norm=0.42,
            trade_count=30,
            high_24h=110.0,
            low_24h=90.0,
            atr=1.0,
            vwap=101.3,
            ema_50=101.2,
            ema_200=95.0,
            ema_50_slope=0.08,
            recent_prices=[96.0, 97.8, 99.2, 100.4, 101.6, 100.8, 101.2, 101.4],
            regime_advisory={
                "suggestedRegime": "TREND_CONTINUATION",
                "confidenceScore": 90,
                "stabilityScore": 84,
                "persistenceScore": 83,
                "dataQuality": {"status": "GOOD", "supportedKeyWindows": True},
            },
        ),
        cfg,
    )
    assert decision["effective_strategy"] == "mean_reversion"
    assert decision["auto_fallback_reason"] == "route_not_promoted"


def test_auto_trend_route_allowed_when_promoted():
    cfg = _base_cfg()
    cfg["token_regimes"] = {"TEST-USD": "AUTO"}
    cfg["market_regime"]["min_score_to_buy"] = 0
    cfg["strategy_defaults"] = {
        "router": {
            "auto_use_multitimeframe_advisory": True,
            "trend_min_closed_trades": 1,
            "trend_min_win_rate_pct": 1,
            "trend_min_expectancy_usd": 0,
        }
    }
    write_json_file(
        se.STATE_DIR / "trades.json",
        [
            {
                "time": se.time.time() - 3600,
                "symbol": "TEST-USD",
                "side": "SELL",
                "reason": "trend_pullback_exit",
                "pnl": 1.5,
            }
        ],
    )

    decision = se.generate_decision(
        _snapshot(
            price=101.4,
            momentum_norm=0.42,
            trade_count=30,
            high_24h=110.0,
            low_24h=90.0,
            atr=1.0,
            vwap=101.3,
            ema_50=101.2,
            ema_200=95.0,
            ema_50_slope=0.08,
            recent_prices=[96.0, 97.8, 99.2, 100.4, 101.6, 100.8, 101.2, 101.4],
            regime_advisory={
                "suggestedRegime": "TREND_CONTINUATION",
                "confidenceScore": 90,
                "stabilityScore": 84,
                "persistenceScore": 83,
                "dataQuality": {"status": "GOOD", "supportedKeyWindows": True},
            },
        ),
        cfg,
    )
    assert decision["effective_strategy"] == "trend_pullback"
    assert decision["reason"] == "trend_pullback_entry"


def test_auto_respects_manual_scalper_override_even_with_strong_regime_signal():
    cfg = _base_cfg()
    cfg["token_regimes"] = {"TEST-USD": "AUTO"}
    cfg["symbol_strategies"] = {"TEST-USD": "volatility_scalper"}
    cfg["volatility_scalper"] = {"symbols": ["TEST-USD"]}
    cfg["market_regime"]["min_score_to_buy"] = 0
    cfg["strategy_defaults"] = {"router": {"auto_use_multitimeframe_advisory": True}}

    decision = se.generate_decision(
        _snapshot(
            price=101.4,
            momentum_norm=0.42,
            trade_count=30,
            high_24h=110.0,
            low_24h=90.0,
            atr=1.0,
            vwap=101.3,
            ema_50=101.2,
            ema_200=95.0,
            ema_50_slope=0.08,
            recent_prices=[96.0, 97.8, 99.2, 100.4, 101.6, 100.8, 101.2, 101.4],
            regime_advisory={
                "suggestedRegime": "TREND_CONTINUATION",
                "confidenceScore": 88,
                "stabilityScore": 82,
                "persistenceScore": 81,
                "dataQuality": {"status": "GOOD", "supportedKeyWindows": True},
            },
        ),
        cfg,
    )
    assert decision["effective_strategy"] == "volatility_scalper"
    assert decision["effective_route"] == "volatility_scalper"
    assert decision.get("fallback_reason") == "manual_scalper_override"


def test_auto_ignores_snapshot_advisory_when_multitimeframe_flag_disabled():
    cfg = _base_cfg()
    cfg["token_regimes"] = {"TEST-USD": "AUTO"}
    decision = se.generate_decision(
        _snapshot(
            regime_advisory={
                "suggestedRegime": "TREND_CONTINUATION",
                "confidenceScore": 92,
            },
        ),
        cfg,
    )
    assert decision["configured_regime"] == "AUTO"
    assert decision["effective_strategy"] == "mean_reversion"
    assert decision["auto_fallback_reason"] == "insufficient_shadow_state"


def test_auto_can_use_current_cycle_shadow_when_enabled():
    cfg = _base_cfg()
    cfg["token_regimes"] = {"TEST-USD": "AUTO"}
    cfg["market_regime"]["min_score_to_buy"] = 0
    cfg["strategy_defaults"] = {
        "router": {
            "auto_use_current_cycle_shadow": True,
            "auto_min_confirmations": 1,
            "auto_min_confidence": 35,
            "auto_min_stability": 30,
            "auto_min_persistence": 30,
            "auto_trend_min_confidence": 35,
            "auto_trend_min_stability": 30,
            "auto_trend_min_persistence": 30,
            "auto_use_route_quality_gates": False,
        }
    }
    decision = se.generate_decision(
        _snapshot(
            price=101.4,
            momentum_norm=0.42,
            trade_count=30,
            high_24h=110.0,
            low_24h=90.0,
            atr=1.0,
            vwap=101.3,
            ema_50=101.2,
            ema_200=95.0,
            ema_50_slope=0.08,
            recent_prices=[96.0, 97.8, 99.2, 100.4, 101.6, 100.8, 101.2, 101.4],
        ),
        cfg,
    )
    assert decision["configured_regime"] == "AUTO"
    assert decision["effective_strategy"] == "trend_pullback"
    assert decision["reason"] == "trend_pullback_entry"


def test_auto_exposes_route_and_regime_timestamps():
    cfg = _base_cfg()
    cfg["token_regimes"] = {"TEST-USD": "AUTO"}
    cfg["market_regime"]["min_score_to_buy"] = 0
    cfg["strategy_defaults"] = {
        "router": {
            "auto_use_multitimeframe_advisory": True,
            "auto_min_confidence": 70,
            "auto_min_stability": 55,
            "auto_min_persistence": 55,
            "auto_use_route_quality_gates": False,
        },
    }
    anchor_epoch = se.time.time()
    decision = se.generate_decision(
        _snapshot(
            regime_advisory={
                "suggestedRegime": "TREND_CONTINUATION",
                "confidenceScore": 88,
                "stabilityScore": 80,
                "persistenceScore": 79,
                "analysisAnchorEpoch": anchor_epoch,
                "dataQuality": {"status": "GOOD", "supportedKeyWindows": True},
            },
        ),
        cfg,
    )
    assert decision["configured_regime"] == "AUTO"
    assert decision["suggested_regime_v2"] == "TREND_CONTINUATION"
    assert decision["effective_route"] == "trend_pullback"
    assert abs(float(decision["regime_eval_ts"]) - anchor_epoch) < 2.0
    assert decision["route_eval_ts"] is not None


def test_auto_falls_back_on_low_stability_and_persistence():
    cfg = _base_cfg()
    cfg["token_regimes"] = {"TEST-USD": "AUTO"}
    cfg["strategy_defaults"] = {"router": {"auto_use_multitimeframe_advisory": True}}
    decision = se.generate_decision(
        _snapshot(
            regime_advisory={
                "suggestedRegime": "TREND_CONTINUATION",
                "confidenceScore": 90,
                "stabilityScore": 40,
                "persistenceScore": 41,
                "dataQuality": {"status": "GOOD", "supportedKeyWindows": True},
            },
        ),
        cfg,
    )
    assert decision["effective_strategy"] == "mean_reversion"
    assert decision["fallback_reason"] in {"low_stability", "low_persistence"}


def test_auto_falls_back_when_route_timestamp_is_stale():
    cfg = _base_cfg()
    cfg["token_regimes"] = {"TEST-USD": "AUTO"}
    cfg["strategy_defaults"] = {
        "router": {
            "auto_use_multitimeframe_advisory": True,
            "auto_max_route_age_seconds": 120,
            "auto_min_confidence": 70,
            "auto_min_stability": 55,
            "auto_min_persistence": 55,
        },
    }
    stale_epoch = (se.time.time() - 600)
    decision = se.generate_decision(
        _snapshot(
            regime_advisory={
                "suggestedRegime": "TREND_CONTINUATION",
                "confidenceScore": 88,
                "stabilityScore": 82,
                "persistenceScore": 80,
                "analysisAnchorEpoch": stale_epoch,
                "dataQuality": {"status": "GOOD", "supportedKeyWindows": True},
            },
        ),
        cfg,
    )
    assert decision["effective_strategy"] == "mean_reversion"
    assert decision["fallback_reason"] == "route_timestamp_stale"


def test_auto_falls_back_when_core_timeframes_not_ready():
    cfg = _base_cfg()
    cfg["token_regimes"] = {"TEST-USD": "AUTO"}
    cfg["strategy_defaults"] = {
        "router": {
            "auto_use_multitimeframe_advisory": True,
            "auto_use_route_quality_gates": False,
            "auto_require_core_candle_readiness": True,
        }
    }
    decision = se.generate_decision(
        _snapshot(
            regime_advisory={
                "suggestedRegime": "TREND_CONTINUATION",
                "confidenceScore": 90,
                "stabilityScore": 84,
                "persistenceScore": 83,
                "dataQuality": {"status": "GOOD", "supportedKeyWindows": True},
            },
            core_candle_readiness={
                "ready": False,
                "reason": "1h:insufficient_depth,4h:insufficient_depth,1d:stale",
            },
        ),
        cfg,
    )
    assert decision["effective_strategy"] == "mean_reversion"
    assert decision["auto_fallback_reason"] == "core_timeframe_not_ready"


def test_auto_accepts_human_readable_suggested_regime_label():
    cfg = _base_cfg()
    cfg["token_regimes"] = {"TEST-USD": "AUTO"}
    cfg["market_regime"]["min_score_to_buy"] = 0
    cfg["strategy_defaults"] = {
        "router": {
            "auto_use_multitimeframe_advisory": True,
            "auto_use_route_quality_gates": False,
            "auto_min_confidence": 60,
            "auto_min_stability": 50,
            "auto_min_persistence": 50,
            "auto_trend_min_confidence": 60,
            "auto_trend_min_stability": 50,
            "auto_trend_min_persistence": 50,
        }
    }
    decision = se.generate_decision(
        _snapshot(
            price=101.4,
            momentum_norm=0.42,
            trade_count=30,
            high_24h=110.0,
            low_24h=90.0,
            atr=1.0,
            vwap=101.3,
            ema_50=101.2,
            ema_200=95.0,
            ema_50_slope=0.08,
            regime_advisory={
                "suggestedRegime": "Trend Continuation / Pullback",
                "confidenceScore": 82,
                "stabilityScore": 78,
                "persistenceScore": 77,
                "dataQuality": {"status": "GOOD", "supportedKeyWindows": True},
            },
        ),
        cfg,
    )
    assert decision["effective_route"] == "trend_pullback"


def test_auto_distribution_regime_stays_mean_reversion():
    cfg = _base_cfg()
    cfg["token_regimes"] = {"TEST-USD": "AUTO"}
    cfg["strategy_defaults"] = {
        "router": {
            "auto_use_multitimeframe_advisory": True,
            "auto_use_route_quality_gates": False,
        }
    }
    decision = se.generate_decision(
        _snapshot(
            regime_advisory={
                "suggestedRegime": "DISTRIBUTION",
                "confidenceScore": 92,
                "stabilityScore": 83,
                "persistenceScore": 82,
                "dataQuality": {"status": "GOOD", "supportedKeyWindows": True},
            },
        ),
        cfg,
    )
    assert decision["effective_route"] == "mean_reversion"
    assert decision["fallback_reason"] == "distribution_defensive"


def test_auto_falls_back_when_key_window_support_flag_missing():
    cfg = _base_cfg()
    cfg["token_regimes"] = {"TEST-USD": "AUTO"}
    cfg["strategy_defaults"] = {
        "router": {
            "auto_use_multitimeframe_advisory": True,
            "auto_use_route_quality_gates": False,
            "auto_min_confidence": 60,
            "auto_min_stability": 50,
            "auto_min_persistence": 50,
        }
    }
    decision = se.generate_decision(
        _snapshot(
            regime_advisory={
                "suggestedRegime": "TREND_CONTINUATION",
                "confidenceScore": 88,
                "stabilityScore": 84,
                "persistenceScore": 82,
                # intentionally missing supportedKeyWindows
                "dataQuality": {"status": "GOOD"},
            },
        ),
        cfg,
    )
    assert decision["effective_strategy"] == "mean_reversion"
    assert decision["fallback_reason"] == "unsupported_key_windows"


def test_manual_trend_missing_data_quality_is_conservative():
    cfg = _base_cfg()
    cfg["token_regimes"] = {"TEST-USD": "TREND_PULLBACK"}
    cfg["market_regime"]["min_score_to_buy"] = 0
    snap = _snapshot(
        price=101.4,
        momentum_norm=0.4,
        trade_count=30,
        high_24h=110.0,
        low_24h=90.0,
        atr=1.0,
        vwap=101.3,
        ema_50=101.2,
        ema_200=95.0,
        ema_50_slope=0.08,
        recent_prices=[96.0, 97.8, 99.2, 100.4, 101.6, 100.8, 101.2, 101.4],
    )
    snap.pop("data_quality_ok", None)
    snap.pop("data_quality_reason", None)

    decision = se.generate_decision(snap, cfg)
    assert decision["action"] == "HOLD"
    assert decision["reason"] == "data_quality_missing"


def test_manual_breakout_missing_data_quality_is_conservative():
    cfg = _base_cfg()
    cfg["token_regimes"] = {"TEST-USD": "BREAKOUT_MOMENTUM"}
    cfg["market_regime"]["min_score_to_buy"] = 0
    snap = _snapshot(
        price=109.9,
        momentum_norm=0.85,
        trade_count=45,
        high_24h=110.0,
        low_24h=100.0,
        atr=1.0,
        vwap=108.0,
        rsi=78.0,
        ema_50=107.5,
        ema_200=104.0,
        recent_prices=[103.0, 104.5, 105.2, 106.3, 107.1, 108.2, 109.0, 109.9],
    )
    snap.pop("data_quality_ok", None)
    snap.pop("data_quality_reason", None)

    decision = se.generate_decision(snap, cfg)
    assert decision["action"] == "HOLD"
    assert decision["reason"] == "data_quality_missing"


def test_manual_scalper_uses_scalper_blocked_regimes_not_mr_defaults(monkeypatch):
    cfg = _base_cfg()
    cfg["token_regimes"] = {"TEST-USD": "AUTO"}
    cfg["symbol_strategies"] = {"TEST-USD": "volatility_scalper"}
    cfg["market_regime"]["blocked_regimes"] = ["range"]
    cfg["market_regime"]["hard_blocked_regimes"] = ["range"]
    cfg["volatility_scalper"] = {
        "symbols": ["TEST-USD"],
        "blocked_regimes": [],
        "min_score_to_buy": 0,
    }

    monkeypatch.setattr(
        se,
        "_compute_scalper_diagnostics",
        lambda **kwargs: ("range", 90.0, 0.3, 0.01),
    )

    decision = se.generate_decision(
        _snapshot(
            price=0.95,
            vwap=1.0,
            atr=0.02,
            momentum_norm=0.7,
            trade_count=60,
            high_24h=1.30,
            low_24h=0.80,
            spread_bps=20.0,
            rsi=50.0,
        ),
        cfg,
    )
    assert decision["effective_strategy"] == "volatility_scalper"
    assert decision["action"] == "BUY"
    assert decision["reason"] == "volatility_scalper_entry"


def test_manual_scalper_missing_data_quality_is_conservative():
    cfg = _base_cfg()
    cfg["token_regimes"] = {"TEST-USD": "AUTO"}
    cfg["symbol_strategies"] = {"TEST-USD": "volatility_scalper"}
    cfg["volatility_scalper"] = {"symbols": ["TEST-USD"]}
    snap = _snapshot(
        price=0.95,
        vwap=1.0,
        atr=0.02,
        momentum_norm=0.7,
        trade_count=60,
        high_24h=1.30,
        low_24h=0.80,
        spread_bps=20.0,
    )
    snap.pop("data_quality_ok", None)
    snap.pop("data_quality_reason", None)

    decision = se.generate_decision(snap, cfg)
    assert decision["effective_strategy"] == "volatility_scalper"
    assert decision["action"] == "HOLD"
    assert decision["reason"] == "data_quality_missing"


def test_trend_route_gates_read_from_strategy_defaults_route_gates():
    cfg = _base_cfg()
    cfg["token_regimes"] = {"TEST-USD": "TREND_PULLBACK"}
    cfg["market_regime"]["min_score_to_buy"] = 0
    cfg["strategy_defaults"] = {
        "route_gates": {
            "trend_pullback": {
                "min_momentum": 0.95,
                "min_score_to_buy": 0,
            }
        }
    }

    decision = se.generate_decision(
        _snapshot(
            price=101.4,
            momentum_norm=0.4,
            trade_count=30,
            high_24h=110.0,
            low_24h=90.0,
            atr=1.0,
            vwap=101.3,
            ema_50=101.2,
            ema_200=95.0,
            ema_50_slope=0.08,
            recent_prices=[96.0, 97.8, 99.2, 100.4, 101.6, 100.8, 101.2, 101.4],
        ),
        cfg,
    )
    assert decision["effective_strategy"] == "trend_pullback"
    assert decision["action"] == "HOLD"
    assert decision["reason"] == "trend_pullback_momentum_not_ready"


def test_breakout_route_gates_read_from_strategy_defaults_route_gates():
    cfg = _base_cfg()
    cfg["token_regimes"] = {"TEST-USD": "BREAKOUT_MOMENTUM"}
    cfg["market_regime"]["min_score_to_buy"] = 0
    cfg["strategy_defaults"] = {
        "route_gates": {
            "breakout_momentum": {
                "min_momentum": 0.95,
                "min_score_to_buy": 0,
            }
        }
    }

    decision = se.generate_decision(
        _snapshot(
            price=109.9,
            momentum_norm=0.9,
            trade_count=45,
            high_24h=110.0,
            low_24h=100.0,
            atr=1.0,
            vwap=108.0,
            rsi=78.0,
            ema_50=107.5,
            ema_200=104.0,
            recent_prices=[103.0, 104.5, 105.2, 106.3, 107.1, 108.2, 109.0, 109.9],
        ),
        cfg,
    )
    assert decision["effective_strategy"] == "breakout_momentum"
    assert decision["action"] == "HOLD"
    assert decision["reason"] == "breakout_momentum_not_ready"
