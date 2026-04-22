from __future__ import annotations

import time
from typing import Any


def _as_float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _as_int(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _route_bucket(state: dict, symbol: str, route: str) -> dict:
    symbol_key = str(symbol or "").strip().upper()
    route_key = str(route or "").strip().lower() or "mean_reversion"
    symbol_row = state.setdefault(symbol_key, {})
    bucket = symbol_row.setdefault(
        route_key,
        {
            "trades": 0,
            "wins": 0,
            "losses": 0,
            "sum_pnl_pct": 0.0,
            "sum_win_pct": 0.0,
            "sum_loss_pct": 0.0,
            "sum_hold_seconds": 0.0,
            "expectancy_pct": 0.0,
            "last_updated_ts": 0.0,
        },
    )
    return bucket


def _compute_expectancy(bucket: dict) -> float:
    trades = max(_as_int(bucket.get("trades"), 0), 0)
    if trades <= 0:
        return 0.0
    wins = max(_as_int(bucket.get("wins"), 0), 0)
    losses = max(_as_int(bucket.get("losses"), 0), 0)
    avg_win = _as_float(bucket.get("sum_win_pct"), 0.0) / max(wins, 1)
    avg_loss = _as_float(bucket.get("sum_loss_pct"), 0.0) / max(losses, 1)
    win_rate = wins / max(trades, 1)
    return (win_rate * avg_win) + ((1.0 - win_rate) * avg_loss)


def record_route_outcome(
    *,
    state: dict,
    symbol: str,
    route: str,
    pnl_pct: float,
    hold_seconds: float,
    now_ts: float | None = None,
) -> dict:
    bucket = _route_bucket(state, symbol, route)
    pnl = _as_float(pnl_pct, 0.0)
    hold = max(_as_float(hold_seconds, 0.0), 0.0)
    bucket["trades"] = _as_int(bucket.get("trades"), 0) + 1
    bucket["sum_pnl_pct"] = _as_float(bucket.get("sum_pnl_pct"), 0.0) + pnl
    bucket["sum_hold_seconds"] = _as_float(bucket.get("sum_hold_seconds"), 0.0) + hold
    if pnl > 0:
        bucket["wins"] = _as_int(bucket.get("wins"), 0) + 1
        bucket["sum_win_pct"] = _as_float(bucket.get("sum_win_pct"), 0.0) + pnl
    else:
        bucket["losses"] = _as_int(bucket.get("losses"), 0) + 1
        bucket["sum_loss_pct"] = _as_float(bucket.get("sum_loss_pct"), 0.0) + pnl
    bucket["expectancy_pct"] = round(_compute_expectancy(bucket), 6)
    bucket["last_updated_ts"] = float(now_ts if now_ts is not None else time.time())
    return bucket


def adaptive_threshold_delta(*, route: str, route_stats: dict | None) -> float:
    stats = route_stats if isinstance(route_stats, dict) else {}
    trades = max(_as_int(stats.get("trades"), 0), 0)
    expectancy = _as_float(stats.get("expectancy_pct"), 0.0)
    route_key = str(route or "").strip().lower()

    if route_key not in {"trend_pullback", "breakout_momentum"} or trades < 10:
        return 0.0

    if expectancy >= 0.020:
        return -4.0
    if expectancy >= 0.010:
        return -2.0
    if expectancy <= -0.020:
        return 6.0
    if expectancy <= -0.010:
        return 3.0
    return 0.0
