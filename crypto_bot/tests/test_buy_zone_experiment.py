from __future__ import annotations

from crypto_bot.tools.buy_zone_experiment import _build_comparison, _window_metrics


def test_window_metrics_computes_entry_exit_and_pnl_fields():
    decision_rows = [
        {"ts_epoch": 100.0, "executed": False, "decision_reason": "price_above_buy_zone"},
        {"ts_epoch": 110.0, "executed": False, "decision_reason": "waiting_for_first_lock"},
        {"ts_epoch": 120.0, "executed": True, "decision_reason": "bear_market_mean_reversion_buy"},
    ]
    trade_rows = [
        {"time": 130.0, "side": "SELL", "pnl": 12.5, "balance": 10012.5},
        {"time": 140.0, "side": "SELL", "pnl": -2.5, "balance": 10010.0},
    ]

    report = _window_metrics(
        start_ts=90.0,
        end_ts=200.0,
        decision_rows=decision_rows,
        trade_rows=trade_rows,
    )

    assert report["total_cycles"] == 3
    assert report["trades_executed"] == 1
    assert report["entry_blocked_cycles"] == 1
    assert report["exit_hold_cycles"] == 1
    assert report["entry_opportunities"] == 2
    assert report["executed_opportunity_rate_pct"] == 50.0
    assert report["realized_net_pnl_usd"] == 10.0
    assert report["sell_count"] == 2


def test_build_comparison_deltas_are_computed():
    before = {
        "executed_opportunity_rate_pct": 1.0,
        "entry_blocked_cycles": 100,
        "trades_executed": 2,
        "realized_net_pnl_usd": 5.0,
        "max_drawdown_pct": 3.0,
        "max_drawdown_usd": 50.0,
    }
    after = {
        "executed_opportunity_rate_pct": 2.5,
        "entry_blocked_cycles": 90,
        "trades_executed": 4,
        "realized_net_pnl_usd": 6.0,
        "max_drawdown_pct": 2.0,
        "max_drawdown_usd": 40.0,
    }
    delta = _build_comparison(before, after)
    assert delta["executed_opportunity_rate_pct_delta"] == 1.5
    assert delta["entry_blocked_cycles_delta"] == -10.0
    assert delta["trades_executed_delta"] == 2.0
    assert delta["realized_net_pnl_usd_delta"] == 1.0
    assert delta["max_drawdown_pct_delta"] == -1.0
    assert delta["max_drawdown_usd_delta"] == -10.0

