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
    ):
        getattr(se, mapping_name).clear()

    monkeypatch.setattr(se, "STRATEGY_STATE_FILE", tmp_path / "strategy_state.json")
    monkeypatch.setattr(se, "PAPER_STATE_FILE", tmp_path / "paper_state.json")
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


def test_volatility_scalper_buy_regression():
    cfg = _base_cfg()
    cfg["symbol_strategies"] = {"GST-USD": "volatility_scalper"}
    cfg["volatility_scalper"] = {"symbols": ["GST-USD"]}

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

    assert decision["action"] == "BUY"
    assert decision["reason"] == "volatility_scalper_entry"
