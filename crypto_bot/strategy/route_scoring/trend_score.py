from __future__ import annotations

from typing import Any


def _as_float(value: Any, default: float | None = None) -> float | None:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return default
    if parsed != parsed:
        return default
    return parsed


def compute_trend_score_bundle(
    *,
    snapshot: dict[str, Any],
    price: float,
    momentum: float,
    high_24h: float,
    low_24h: float,
    atr: float | None,
) -> tuple[str, float, float | None, float | None]:
    range_pos = None
    if high_24h > low_24h:
        range_pos = (price - low_24h) / (high_24h - low_24h)
        range_pos = max(0.0, min(1.0, range_pos))

    ema_50 = _as_float(snapshot.get("ema_50"))
    ema_200 = _as_float(snapshot.get("ema_200"))
    ema_50_slope = _as_float(snapshot.get("ema_50_slope"), 0.0) or 0.0
    momentum_val = _as_float(momentum, 0.0) or 0.0

    score = 35.0
    if ema_50 is not None and ema_200 is not None and ema_50 > ema_200:
        score += 30.0
    if ema_50_slope > 0:
        score += min(15.0, ema_50_slope * 100.0)
    if momentum_val > 0:
        score += min(20.0, momentum_val * 20.0)
    if range_pos is not None and 0.25 <= range_pos <= 0.85:
        score += 10.0

    score = max(0.0, min(100.0, score))
    volatility = _as_float(atr, default=None)
    return "trend_pullback", float(score), range_pos, volatility
