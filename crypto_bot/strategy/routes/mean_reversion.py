from __future__ import annotations

from typing import Any, Callable

from strategy.data_quality_gate import evaluate_entry_data_quality


def evaluate_mean_reversion_entry(
    *,
    snapshot: dict[str, Any],
    symbol: str,
    price: float,
    momentum: float,
    trades: int,
    high_24h: float,
    low_24h: float,
    atr: float | None,
    vwap: float | None,
    z_score: float | None,
    prev_mom: float | None,
    min_trades: int,
    min_atr: float,
    buy_zone_low: float,
    buy_zone_high: float,
    min_z_score: float,
    min_score_to_buy: float,
    blocked_regimes: set[str],
    regime: str,
    score: float,
    range_pos: float | None,
    last_momentum_state: dict[str, float],
    decision: Callable[[str, str, float, float, str], dict[str, Any]],
    cfg: dict[str, Any] | None = None,
) -> dict[str, Any]:
    data_quality_allowed, blocked_reason = evaluate_entry_data_quality(
        snapshot=snapshot,
        cfg=cfg,
    )
    if not data_quality_allowed:
        return decision(
            symbol,
            "HOLD",
            price,
            momentum,
            str(blocked_reason or "data_quality_failed"),
        )

    if (
        trades < min_trades
        or high_24h <= low_24h
        or vwap is None
        or atr is None
        or atr <= 0
    ):
        return decision(symbol, "HOLD", price, momentum, "insufficient_data")

    if atr < min_atr:
        return decision(symbol, "HOLD", price, momentum, "atr_too_low")

    if z_score is None:
        z_score = (price - vwap) / atr

    if regime in blocked_regimes:
        return decision(symbol, "HOLD", price, momentum, f"regime_{regime}")

    if range_pos is None:
        return decision(symbol, "HOLD", price, momentum, "insufficient_range_data")

    if range_pos > buy_zone_high:
        return decision(symbol, "HOLD", price, momentum, "price_above_buy_zone")

    if range_pos < buy_zone_low:
        return decision(symbol, "HOLD", price, momentum, "price_below_buy_zone")

    if z_score > min_z_score:
        return decision(symbol, "HOLD", price, momentum, "insufficient_volatility_stretch")

    if score < min_score_to_buy:
        return decision(symbol, "HOLD", price, momentum, "score_below_threshold")

    if prev_mom is not None and momentum < prev_mom:
        last_momentum_state[symbol] = momentum
        return decision(symbol, "HOLD", price, momentum, "momentum_still_falling")

    last_momentum_state[symbol] = momentum
    return decision(symbol, "BUY", price, momentum, "bear_market_mean_reversion_buy")
