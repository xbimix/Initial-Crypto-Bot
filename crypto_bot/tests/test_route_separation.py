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
        "price": 100.0,
        "momentum_norm": 0.4,
        "trade_count": 30,
        "high_24h": 110.0,
        "low_24h": 90.0,
        "atr": 1.0,
        "vwap": 99.5,
        "rsi": 45.0,
        "spread_bps": 10.0,
        "recent_prices": [95.0, 96.0, 97.0, 98.0, 99.0, 100.0, 101.0, 102.0],
        "ema_50": 101.0,
        "ema_200": 95.0,
        "ema_50_slope": 0.05,
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
        "_entry_route",
        "_entry_regime",
        "_exit_policy",
        "_entry_confidence",
        "_entry_timestamp",
        "_entry_route_eval_ts",
        "_entry_regime_eval_ts",
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


def test_open_position_keeps_stored_exit_policy(monkeypatch):
    cfg = _base_cfg()
    cfg["token_regimes"] = {"TEST-USD": "AUTO"}

    se.confirm_entry(
        "TEST-USD",
        100.0,
        entry_route="trend_pullback",
        exit_policy="trend_exit",
        entry_regime="TREND_CONTINUATION",
    )

    monkeypatch.setattr(
        se,
        "resolve_entry_route",
        lambda **kwargs: {
            "configured_regime": "AUTO",
            "detected_regime": "MEAN_REVERSION_FRIENDLY",
            "effective_strategy": "mean_reversion",
            "effective_route": "mean_reversion",
            "route_eval_ts": 1000.0,
            "regime_eval_ts": 1000.0,
        },
    )
    monkeypatch.setattr(se, "_compute_buy_diagnostics", lambda **kwargs: ("range", 50.0, 0.5, 0.01))
    monkeypatch.setattr(se, "_record_shadow_regime_metrics", lambda **kwargs: None)
    monkeypatch.setattr(se, "_record_symbol_metrics", lambda *args, **kwargs: None)
    monkeypatch.setattr(se, "_flush_metrics_state_if_due", lambda: None)

    observed = {"trend_exit": 0, "mr_exit": 0}

    def _trend_exit(**kwargs):
        observed["trend_exit"] += 1
        return se._decision("TEST-USD", "HOLD", 100.0, 0.4, "trend_exit_hold")

    def _mr_exit(**kwargs):
        observed["mr_exit"] += 1
        return se._decision("TEST-USD", "HOLD", 100.0, 0.4, "mr_exit_hold")

    monkeypatch.setattr(se, "evaluate_trend_exit", _trend_exit)
    monkeypatch.setattr(se, "evaluate_mr_exit", _mr_exit)

    decision = se.generate_decision(_snapshot(), cfg)
    assert decision["action"] == "HOLD"
    assert decision["reason"] == "trend_exit_hold"
    assert observed["trend_exit"] == 1
    assert observed["mr_exit"] == 0
    assert decision["effective_strategy"] == "trend_pullback"


def test_auto_route_used_for_entry_then_open_position_keeps_policy(monkeypatch):
    cfg = _base_cfg()
    cfg["token_regimes"] = {"TEST-USD": "AUTO"}

    monkeypatch.setattr(
        se,
        "resolve_entry_route",
        lambda **kwargs: {
            "configured_regime": "AUTO",
            "detected_regime": "TREND_CONTINUATION",
            "suggested_regime_v2": "TREND_CONTINUATION",
            "detected_regime_confidence": 88.0,
            "effective_strategy": "trend_pullback",
            "effective_route": "trend_pullback",
            "route_eval_ts": 2000.0,
            "regime_eval_ts": 1999.0,
        },
    )
    monkeypatch.setattr(se, "compute_trend_score_bundle", lambda **kwargs: ("trend_pullback", 90.0, 0.6, 1.0))
    monkeypatch.setattr(se, "_record_shadow_regime_metrics", lambda **kwargs: None)
    monkeypatch.setattr(se, "_record_symbol_metrics", lambda *args, **kwargs: None)
    monkeypatch.setattr(se, "_flush_metrics_state_if_due", lambda: None)
    monkeypatch.setattr(
        se,
        "_evaluate_trend_pullback_buy",
        lambda **kwargs: se._decision("TEST-USD", "BUY", 100.0, 0.4, "trend_pullback_entry"),
    )

    buy_decision = se.generate_decision(_snapshot(), cfg)
    assert buy_decision["action"] == "BUY"
    assert buy_decision["entry_route"] == "trend_pullback"
    assert buy_decision["exit_policy"] == "trend_exit"

    se.confirm_entry(
        "TEST-USD",
        100.0,
        entry_route=buy_decision.get("entry_route"),
        entry_regime=buy_decision.get("entry_regime"),
        exit_policy=buy_decision.get("exit_policy"),
        entry_confidence=buy_decision.get("entry_confidence"),
        entry_timestamp=buy_decision.get("entry_timestamp"),
        route_eval_ts=buy_decision.get("entry_route_eval_ts"),
        regime_eval_ts=buy_decision.get("entry_regime_eval_ts"),
    )

    monkeypatch.setattr(
        se,
        "resolve_entry_route",
        lambda **kwargs: {
            "configured_regime": "AUTO",
            "detected_regime": "MEAN_REVERSION_FRIENDLY",
            "effective_strategy": "mean_reversion",
            "effective_route": "mean_reversion",
            "route_eval_ts": 3000.0,
            "regime_eval_ts": 2999.0,
        },
    )
    monkeypatch.setattr(
        se,
        "evaluate_trend_exit",
        lambda **kwargs: se._decision("TEST-USD", "HOLD", 100.0, 0.4, "trend_exit_hold"),
    )

    hold_decision = se.generate_decision(_snapshot(price=101.0), cfg)
    assert hold_decision["action"] == "HOLD"
    assert hold_decision["reason"] == "trend_exit_hold"
    assert hold_decision["effective_strategy"] == "trend_pullback"


def test_trend_and_breakout_paths_do_not_call_mr_score(monkeypatch):
    cfg = _base_cfg()
    cfg["token_regimes"] = {"TEST-USD": "TREND_PULLBACK"}

    monkeypatch.setattr(
        se,
        "compute_mr_score_bundle",
        lambda **kwargs: (_ for _ in ()).throw(AssertionError("MR score must not be used")),
    )
    monkeypatch.setattr(se, "compute_trend_score_bundle", lambda **kwargs: ("trend_pullback", 92.0, 0.55, 1.0))
    monkeypatch.setattr(se, "_record_shadow_regime_metrics", lambda **kwargs: None)
    monkeypatch.setattr(se, "_record_symbol_metrics", lambda *args, **kwargs: None)
    monkeypatch.setattr(se, "_flush_metrics_state_if_due", lambda: None)
    monkeypatch.setattr(
        se,
        "_evaluate_trend_pullback_buy",
        lambda **kwargs: se._decision("TEST-USD", "BUY", 100.0, 0.4, "trend_pullback_entry"),
    )

    trend_decision = se.generate_decision(_snapshot(), cfg)
    assert trend_decision["action"] == "BUY"
    assert trend_decision["effective_strategy"] == "trend_pullback"

    cfg["token_regimes"] = {"TEST-USD": "BREAKOUT_MOMENTUM"}
    monkeypatch.setattr(se, "compute_breakout_score_bundle", lambda **kwargs: ("breakout_momentum", 93.0, 0.8, 1.2))
    monkeypatch.setattr(
        se,
        "_evaluate_breakout_momentum_buy",
        lambda **kwargs: se._decision("TEST-USD", "BUY", 100.0, 0.6, "breakout_momentum_entry"),
    )

    breakout_decision = se.generate_decision(_snapshot(momentum_norm=0.6), cfg)
    assert breakout_decision["action"] == "BUY"
    assert breakout_decision["effective_strategy"] == "breakout_momentum"


def test_legacy_open_position_without_route_metadata_uses_mr_exit(monkeypatch):
    cfg = _base_cfg()
    cfg["token_regimes"] = {"TEST-USD": "AUTO"}

    se._entry_price["TEST-USD"] = 100.0
    se._entry_time["TEST-USD"] = 1000.0
    se._last_signal["TEST-USD"] = "BUY"

    monkeypatch.setattr(
        se,
        "resolve_entry_route",
        lambda **kwargs: {
            "configured_regime": "AUTO",
            "detected_regime": "BREAKOUT_EXPANSION",
            "effective_strategy": "breakout_momentum",
            "effective_route": "breakout_momentum",
            "route_eval_ts": 2000.0,
            "regime_eval_ts": 1999.0,
        },
    )
    monkeypatch.setattr(se, "compute_mr_score_bundle", lambda **kwargs: ("range", 50.0, 0.5, 1.0))
    monkeypatch.setattr(se, "_record_shadow_regime_metrics", lambda **kwargs: None)
    monkeypatch.setattr(se, "_record_symbol_metrics", lambda *args, **kwargs: None)
    monkeypatch.setattr(se, "_flush_metrics_state_if_due", lambda: None)

    observed = {"mr_exit": 0, "breakout_exit": 0}

    def _mr_exit(**kwargs):
        observed["mr_exit"] += 1
        return se._decision("TEST-USD", "HOLD", 100.0, 0.4, "mr_exit_hold")

    def _breakout_exit(**kwargs):
        observed["breakout_exit"] += 1
        return se._decision("TEST-USD", "HOLD", 100.0, 0.4, "breakout_exit_hold")

    monkeypatch.setattr(se, "evaluate_mr_exit", _mr_exit)
    monkeypatch.setattr(se, "evaluate_breakout_exit", _breakout_exit)

    decision = se.generate_decision(_snapshot(), cfg)
    assert decision["action"] == "HOLD"
    assert decision["reason"] == "mr_exit_hold"
    assert observed["mr_exit"] == 1
    assert observed["breakout_exit"] == 0


def test_staged_entry_contract_is_consumed_or_cleared():
    se.stage_entry_contract(
        "TEST-USD",
        {
            "entry_route": "trend_pullback",
            "entry_regime": "TREND_CONTINUATION",
            "exit_policy": "trend_exit",
            "entry_confidence": 88.0,
            "entry_timestamp": 1234.0,
            "route_eval_ts": 1235.0,
            "regime_eval_ts": 1233.0,
        },
    )
    assert "TEST-USD" in se._pending_entry_contract

    se.confirm_entry("TEST-USD", 100.0)
    assert "TEST-USD" not in se._pending_entry_contract
    assert se._entry_route["TEST-USD"] == "trend_pullback"
    assert se._exit_policy["TEST-USD"] == "trend_exit"
    assert se._entry_regime["TEST-USD"] == "TREND_CONTINUATION"

    se.stage_entry_contract("TEST-USD", {"entry_route": "breakout_momentum"})
    assert "TEST-USD" in se._pending_entry_contract
    se.clear_entry_contract("TEST-USD")
    assert "TEST-USD" not in se._pending_entry_contract
