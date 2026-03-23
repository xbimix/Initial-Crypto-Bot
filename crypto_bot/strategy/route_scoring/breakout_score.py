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


def compute_breakout_score_bundle(
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

    momentum_val = _as_float(momentum, 0.0) or 0.0
    volatility = _as_float(atr, default=None)
    score = 30.0
    if range_pos is not None:
        if range_pos >= 0.75:
            score += 25.0
        elif range_pos >= 0.6:
            score += 12.0
    if momentum_val > 0:
        score += min(30.0, momentum_val * 25.0)

    recent = snapshot.get("recent_prices", [])
    if isinstance(recent, list) and len(recent) >= 8:
        clean = []
        for item in recent[-8:]:
            value = _as_float(item)
            if value is not None and value > 0:
                clean.append(value)
        if len(clean) >= 8:
            prior = clean[:4]
            now = clean[4:]
            prior_range = max(prior) - min(prior)
            now_range = max(now) - min(now)
            if prior_range > 0 and now_range <= prior_range * 0.95:
                score += 15.0

    score = max(0.0, min(100.0, score))
    return "breakout_momentum", float(score), range_pos, volatility
