from __future__ import annotations

from strategy.regime_engine import normalize_shadow_state, update_regime_shadow_state


def _snapshot(**overrides) -> dict:
    base = {
        "price": 100.0,
        "trade_count": 30,
        "atr": 0.01,
        "momentum_norm": 0.7,
        "spread_bps": 20.0,
        "high_24h": 110.0,
        "low_24h": 90.0,
        "data_quality_ok": True,
    }
    base.update(overrides)
    return base


def test_shadow_switch_requires_confirmation():
    cfg = {"strategy_defaults": {"router": {"confirmations_required": 2}}}
    state = {}

    first, _ = update_regime_shadow_state(
        symbol="ADA-USD",
        snapshot=_snapshot(),
        candidate_regime="range",
        shadow_state=state,
        cfg=cfg,
        now_ts=100.0,
    )
    assert first["stable_regime"] == "range"

    second, _ = update_regime_shadow_state(
        symbol="ADA-USD",
        snapshot=_snapshot(momentum_norm=-2.0),
        candidate_regime="breakout_down",
        shadow_state=state,
        cfg=cfg,
        now_ts=110.0,
    )
    assert second["confirmations"] == 1
    assert second["stable_regime"] == "range"
    assert second["switched"] is False

    third, _ = update_regime_shadow_state(
        symbol="ADA-USD",
        snapshot=_snapshot(momentum_norm=-2.2),
        candidate_regime="breakout_down",
        shadow_state=state,
        cfg=cfg,
        now_ts=120.0,
    )
    assert third["confirmations"] == 2
    assert third["stable_regime"] == "breakout_down"
    assert third["switched"] is True


def test_shadow_switch_respects_cooldown():
    cfg = {
        "strategy_defaults": {
            "router": {
                "confirmations_required": 1,
                "regime_cooldown_seconds": 120,
            }
        }
    }
    state = {}

    start, _ = update_regime_shadow_state(
        symbol="BTC-USD",
        snapshot=_snapshot(),
        candidate_regime="range",
        shadow_state=state,
        cfg=cfg,
        now_ts=200.0,
    )
    assert start["stable_regime"] == "range"

    early, _ = update_regime_shadow_state(
        symbol="BTC-USD",
        snapshot=_snapshot(momentum_norm=-2.0),
        candidate_regime="breakout_down",
        shadow_state=state,
        cfg=cfg,
        now_ts=250.0,
    )
    assert early["stable_regime"] == "range"
    assert early["switched"] is False

    late, _ = update_regime_shadow_state(
        symbol="BTC-USD",
        snapshot=_snapshot(momentum_norm=-2.4),
        candidate_regime="breakout_down",
        shadow_state=state,
        cfg=cfg,
        now_ts=340.0,
    )
    assert late["stable_regime"] == "breakout_down"
    assert late["switched"] is True


def test_shadow_confidence_degrades_for_unknown_poor_quality():
    cfg = {"strategy_defaults": {"router": {"confirmations_required": 1}}}
    state = {}

    row, _ = update_regime_shadow_state(
        symbol="PERP-USD",
        snapshot=_snapshot(
            data_quality_ok=False,
            trade_count=0,
            atr=0.0,
            spread_bps=280.0,
            momentum_norm=0.0,
        ),
        candidate_regime="unknown",
        shadow_state=state,
        cfg=cfg,
        now_ts=500.0,
    )
    assert 0.0 <= row["confidence"] <= 0.25


def test_normalize_shadow_state_sanitizes_input():
    raw = {
        "ada-usd": {
            "candidate_regime": "range",
            "stable_regime": "range",
            "confirmations": "3",
            "confidence": "1.9",
            "last_update_ts": "12.5",
            "last_switch_ts": "-5",
            "switched": "truthy",
        },
        "": {"candidate_regime": "unknown"},
    }
    normalized = normalize_shadow_state(raw)
    assert "ADA-USD" in normalized
    assert "" not in normalized
    row = normalized["ADA-USD"]
    assert row["confirmations"] == 3
    assert row["confidence"] == 0.99
    assert row["last_update_ts"] == 12.5
    assert row["last_switch_ts"] == 0.0
