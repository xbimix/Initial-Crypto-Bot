from __future__ import annotations

from tools import live_safety_tuning_report as report


def test_trade_performance_summary_computes_profit_factor_and_expectancy():
    closed_parts = [
        {"pnl_usd": 10.0, "hold_hours": 2.0},
        {"pnl_usd": -4.0, "hold_hours": 1.0},
        {"pnl_usd": 6.0, "hold_hours": 3.0},
    ]
    trades_rows = [
        {"time": 1, "balance": 1000},
        {"time": 2, "balance": 1010},
        {"time": 3, "balance": 1006},
        {"time": 4, "balance": 1012},
    ]

    summary = report._trade_performance_summary(
        closed_parts,
        trades_rows=trades_rows,
        starting_balance=1000.0,
    )

    assert summary["closed_parts"] == 3
    assert summary["wins"] == 2
    assert summary["losses"] == 1
    assert summary["net_pnl_usd"] == 12.0
    assert summary["profit_factor"] == 4.0
    assert summary["expectancy_per_trade_usd"] == 4.0
    assert summary["max_drawdown_usd"] == 4.0
    assert summary["max_drawdown_pct"] == 0.396


def test_buy_rejection_summary_counts_blocked_reasons():
    rows = [
        {"action": "BUY", "executed": True},
        {"action": "BUY", "executed": False, "blocked_reason": "low_confidence"},
        {"action": "BUY", "executed": False, "decision_reason": "throttle"},
        {"action": "SELL", "executed": True},
    ]
    summary = report._buy_rejection_summary(rows)
    assert summary["buy_attempts"] == 3
    assert summary["buy_executed"] == 1
    assert summary["buy_blocked"] == 2
    assert summary["rejection_rate_pct"] == 66.6667
    assert summary["blocked_reason_counts"]["low_confidence"] == 1
    assert summary["blocked_reason_counts"]["throttle"] == 1


def test_slippage_fee_metrics_handles_missing_fields():
    rows = [
        {"slippage_bps": 5.0, "fee_usd": 0.5, "fill_ratio": 0.9},
        {"slippage_bps": 7.0, "fee_usd": 0.7, "fill_ratio": 0.8},
        {"side": "BUY"},
    ]
    metrics = report._slippage_fee_metrics(rows)
    assert metrics["slippage_samples"] == 2
    assert metrics["avg_slippage_bps"] == 6.0
    assert metrics["avg_fee_usd"] == 0.6
    assert metrics["avg_fill_ratio"] == 0.85
