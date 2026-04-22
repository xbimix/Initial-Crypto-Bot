"""
Legacy indicator scoring module.

Status: compatibility scoring for mean-reversion pathways.
Directional routes should use dedicated trend/breakout score bundles.
"""


def _normalize_regime(regime):
    raw = str(regime or "").strip().lower()
    compat = {
        "accumulation": "low_vol",
        "spike": "breakout_up",
        "dump": "breakout_down",
        "chop": "choppy",
    }
    return compat.get(raw, raw or "unknown")


def _as_float(value, default=None):
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return default
    if parsed != parsed:  # NaN guard
        return default
    return parsed


def score_indicators(regime, indicators, range_pos):
    normalized = _normalize_regime(regime)

    score_range_cap = _as_float(indicators.get("mr_score_max_range_pos"), 0.30)
    if score_range_cap is None:
        score_range_cap = 0.30
    score_range_cap = max(0.0, min(score_range_cap, 1.0))

    # Hard blocks for non-entry or downside regimes in long-only flow.
    if normalized in {"trend_down", "breakout_down", "choppy", "unknown"}:
        return 0.0

    # Keep MR score gating aligned with configured buy-zone envelope.
    if range_pos > score_range_cap and normalized in {"range", "low_vol"}:
        return 0.0

    rsi = float(indicators.get("rsi", 50.0))
    momentum = float(indicators.get("momentum", 0.0))
    structure = float(indicators.get("structure", 0.0))

    # Mean-reversion-oriented base score.
    score = 0.0
    if rsi < 35:
        score += 40.0
    elif rsi < 45:
        score += 20.0
    if momentum > -0.2:
        score += 20.0
    if structure > 0:
        score += 20.0

    # Regime-aware shaping.
    if normalized in {"range", "low_vol"}:
        score += 15.0
    elif normalized in {"trend_up", "momentum_up", "breakout_up", "volatile"}:
        # Do not over-bias MR entries in directional/expanding regimes.
        score *= 0.55

    return max(0.0, min(score, 100.0))
