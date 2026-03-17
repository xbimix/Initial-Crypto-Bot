from __future__ import annotations

from pathlib import Path

import pytest

from strategy import strategy_engine as se


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
        "_last_detection_source",
        "_last_detection_timestamp_epoch",
        "_last_effective_strategy",
        "_last_auto_fallback_reason",
        "_shadow_regime_state",
    ):
        getattr(se, mapping_name).clear()

    monkeypatch.setattr(se, "STRATEGY_STATE_FILE", tmp_path / "strategy_state.json")
    monkeypatch.setattr(se, "PAPER_STATE_FILE", tmp_path / "paper_state.json")
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
            },
        ),
        cfg,
    )
    assert decision["action"] == "BUY"
    assert decision["reason"] == "bear_market_mean_reversion_buy"
    assert decision["effective_strategy"] == "mean_reversion"
    assert decision["auto_fallback_reason"] == "low_confidence"


def test_auto_high_confidence_routes_to_trend_pullback():
    cfg = _base_cfg()
    cfg["token_regimes"] = {"TEST-USD": "AUTO"}
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
                "confidenceScore": 82,
            },
        ),
        cfg,
    )
    assert decision["action"] == "BUY"
    assert decision["reason"] == "trend_pullback_entry"
    assert decision["effective_strategy"] == "trend_pullback"


def test_auto_uses_shadow_high_confidence_when_snapshot_advisory_missing():
    cfg = _base_cfg()
    cfg["token_regimes"] = {"TEST-USD": "AUTO"}
    cfg["market_regime"]["min_score_to_buy"] = 0
    cfg["strategy_defaults"] = {"router": {"auto_min_confirmations": 2}}

    se._shadow_regime_state["TEST-USD"] = {
        "candidate_regime": "trend_up",
        "stable_regime": "trend_up",
        "confirmations": 3,
        "confidence": 0.92,
        "last_update_ts": 100.0,
        "last_switch_ts": 90.0,
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
        "last_update_ts": 100.0,
        "last_switch_ts": 90.0,
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
    cfg["strategy_defaults"] = {"router": {"auto_use_multitimeframe_advisory": True}}

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
            },
        ),
        cfg,
    )
    assert decision["action"] == "BUY"
    assert decision["reason"] == "breakout_momentum_entry"
    assert decision["effective_strategy"] == "breakout_momentum"


def test_auto_respects_legacy_scalper_default():
    cfg = _base_cfg()
    cfg["token_regimes"] = {"TEST-USD": "AUTO"}
    cfg["symbol_strategies"] = {"TEST-USD": "volatility_scalper"}
    cfg["volatility_scalper"] = {"symbols": ["TEST-USD"]}

    decision = se.generate_decision(
        _snapshot(
            price=1.005,
            vwap=1.02,
            atr=0.02,
            momentum_norm=0.5,
            high_24h=1.3,
            low_24h=0.8,
            spread_bps=20.0,
            rsi=50.0,
            recent_prices=[0.98, 0.99, 1.0, 1.01, 1.015, 1.01, 1.005],
            regime_advisory={
                "suggestedRegime": "TREND_CONTINUATION",
                "confidenceScore": 88,
            },
        ),
        cfg,
    )
    assert decision["action"] == "BUY"
    assert decision["reason"] == "volatility_scalper_entry"
    assert decision["effective_strategy"] == "volatility_scalper"
    assert decision["auto_fallback_reason"] == "legacy_scalper_mode"


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
