from __future__ import annotations

from collections import defaultdict
from typing import Any


def _to_float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return float(default)


def _to_bucket(summary: dict[str, Any]) -> dict[str, Any]:
    trade_count = int(summary.get("trade_count", 0) or 0)
    closed_count = int(summary.get("closed_count", 0) or 0)
    wins = int(summary.get("wins", 0) or 0)
    slippage_samples = int(summary.get("slippage_samples", 0) or 0)
    avg_slippage_bps = None
    if slippage_samples > 0:
        avg_slippage_bps = _to_float(summary.get("slippage_bps_sum", 0.0), 0.0) / slippage_samples

    win_rate_pct = None
    if closed_count > 0:
        win_rate_pct = (wins / closed_count) * 100.0

    return {
        "trade_count": trade_count,
        "buy_count": int(summary.get("buy_count", 0) or 0),
        "sell_count": int(summary.get("sell_count", 0) or 0),
        "closed_count": closed_count,
        "realized_pnl_net_usd": round(_to_float(summary.get("realized_pnl_net_usd", 0.0), 0.0), 6),
        "fee_usd": round(_to_float(summary.get("fee_usd", 0.0), 0.0), 6),
        "slippage_usd": round(_to_float(summary.get("slippage_usd", 0.0), 0.0), 6),
        "avg_slippage_bps": (round(avg_slippage_bps, 6) if avg_slippage_bps is not None else None),
        "win_rate_pct": (round(win_rate_pct, 6) if win_rate_pct is not None else None),
    }


def aggregate_execution_metrics(trades: list[dict[str, Any]]) -> dict[str, Any]:
    route_summary: dict[str, dict[str, Any]] = defaultdict(dict)
    strategy_summary: dict[str, dict[str, Any]] = defaultdict(dict)

    def _accumulate(bucket_map: dict[str, dict[str, Any]], key: str, trade: dict[str, Any]):
        bucket = bucket_map.setdefault(key, {})
        side = str(trade.get("side") or "").upper()
        bucket["trade_count"] = int(bucket.get("trade_count", 0) or 0) + 1
        if side == "BUY":
            bucket["buy_count"] = int(bucket.get("buy_count", 0) or 0) + 1
        elif side == "SELL":
            bucket["sell_count"] = int(bucket.get("sell_count", 0) or 0) + 1
            bucket["closed_count"] = int(bucket.get("closed_count", 0) or 0) + 1
            pnl = _to_float(trade.get("realized_pnl_net_usd", trade.get("pnl")), 0.0)
            bucket["realized_pnl_net_usd"] = _to_float(bucket.get("realized_pnl_net_usd"), 0.0) + pnl
            if pnl > 0:
                bucket["wins"] = int(bucket.get("wins", 0) or 0) + 1

        fee = _to_float(trade.get("fee_usd"), 0.0)
        bucket["fee_usd"] = _to_float(bucket.get("fee_usd"), 0.0) + fee
        slippage_usd = _to_float(trade.get("slippage_usd"), 0.0)
        bucket["slippage_usd"] = _to_float(bucket.get("slippage_usd"), 0.0) + slippage_usd
        slippage_bps = trade.get("slippage_bps")
        if slippage_bps is not None:
            bucket["slippage_samples"] = int(bucket.get("slippage_samples", 0) or 0) + 1
            bucket["slippage_bps_sum"] = _to_float(bucket.get("slippage_bps_sum"), 0.0) + _to_float(slippage_bps, 0.0)

    for trade in trades:
        if not isinstance(trade, dict):
            continue
        route = str(
            trade.get("effective_route")
            or trade.get("entry_route")
            or "unknown"
        ).strip().lower() or "unknown"
        strategy = str(
            trade.get("effective_strategy")
            or "unknown"
        ).strip().lower() or "unknown"
        _accumulate(route_summary, route, trade)
        _accumulate(strategy_summary, strategy, trade)

    route_metrics = {key: _to_bucket(value) for key, value in sorted(route_summary.items(), key=lambda item: item[0])}
    strategy_metrics = {key: _to_bucket(value) for key, value in sorted(strategy_summary.items(), key=lambda item: item[0])}
    return {
        "route_level": route_metrics,
        "strategy_level": strategy_metrics,
    }
