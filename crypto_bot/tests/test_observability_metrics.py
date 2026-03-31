from __future__ import annotations

from observability.metrics import aggregate_execution_metrics


def test_aggregate_execution_metrics_by_route_and_strategy():
    trades = [
        {
            "side": "BUY",
            "effective_route": "mean_reversion",
            "effective_strategy": "mean_reversion",
            "fee_usd": 0.3,
            "slippage_usd": 0.1,
            "slippage_bps": 4.0,
        },
        {
            "side": "SELL",
            "effective_route": "mean_reversion",
            "effective_strategy": "mean_reversion",
            "realized_pnl_net_usd": 5.0,
            "fee_usd": 0.2,
            "slippage_usd": 0.1,
            "slippage_bps": 3.0,
        },
        {
            "side": "SELL",
            "effective_route": "trend_pullback",
            "effective_strategy": "trend_pullback",
            "pnl": -2.0,
            "fee_usd": 0.1,
            "slippage_usd": 0.2,
            "slippage_bps": 5.0,
        },
    ]
    metrics = aggregate_execution_metrics(trades)
    route = metrics["route_level"]
    strategy = metrics["strategy_level"]

    assert route["mean_reversion"]["trade_count"] == 2
    assert route["mean_reversion"]["closed_count"] == 1
    assert route["mean_reversion"]["realized_pnl_net_usd"] == 5.0
    assert route["mean_reversion"]["win_rate_pct"] == 100.0
    assert route["trend_pullback"]["realized_pnl_net_usd"] == -2.0
    assert strategy["trend_pullback"]["fee_usd"] == 0.1


def test_aggregate_execution_metrics_handles_missing_fields():
    metrics = aggregate_execution_metrics([{"side": "SELL"}])
    unknown_route = metrics["route_level"]["unknown"]
    assert unknown_route["trade_count"] == 1
    assert unknown_route["closed_count"] == 1
    assert unknown_route["realized_pnl_net_usd"] == 0.0
