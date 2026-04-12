from __future__ import annotations

from strategy import strategy_orchestrator as so


def _decision(symbol, action, price, momentum, reason):
    return {
        "symbol": symbol,
        "action": action,
        "price": price,
        "momentum": momentum,
        "reason": reason,
    }


def _parse_numeric(value, fallback=None):
    try:
        return float(value)
    except (TypeError, ValueError):
        return fallback


def test_scalper_buy_respects_shared_data_quality_gate_default_strict():
    snapshot = {
        "symbol": "BTC-USD",
        "data_quality_ok": False,
        "data_quality_reason": "market_data_quality:partial",
        "data_quality_status": "PARTIAL",
        "data_quality_score": 95.0,
    }
    decision = so._evaluate_scalper_buy(
        snapshot=snapshot,
        symbol="BTC-USD",
        price=100.0,
        momentum=0.5,
        trades=50,
        atr=0.02,
        z_score=-0.4,
        prev_mom=0.1,
        regime="range",
        score=80.0,
        range_pos=0.2,
        blocked_regimes=[],
        min_trades=3,
        scalper_cfg={},
        cfg={"market_data": {"strategy_allow_partial_participation": False}},
        parse_numeric=_parse_numeric,
        decision=_decision,
    )
    assert decision["action"] == "HOLD"
    assert decision["reason"] == "market_data_quality:partial"


def test_scalper_buy_allows_partial_quality_when_score_floor_passes():
    snapshot = {
        "symbol": "BTC-USD",
        "data_quality_ok": False,
        "data_quality_reason": "market_data_quality:partial",
        "data_quality_status": "PARTIAL",
        "data_quality_score": 72.0,
    }
    decision = so._evaluate_scalper_buy(
        snapshot=snapshot,
        symbol="BTC-USD",
        price=100.0,
        momentum=0.5,
        trades=1,
        atr=0.02,
        z_score=-0.4,
        prev_mom=0.1,
        regime="range",
        score=80.0,
        range_pos=0.2,
        blocked_regimes=[],
        min_trades=3,
        scalper_cfg={"min_trades": 6},
        cfg={
            "market_data": {
                "strategy_allow_partial_participation": True,
                "strategy_eval_min_quality_score": 60.0,
            }
        },
        parse_numeric=_parse_numeric,
        decision=_decision,
    )
    assert decision["action"] == "HOLD"
    # Data quality gate passed and the next route guard blocked on trades.
    assert decision["reason"] == "scalper_insufficient_trades"
