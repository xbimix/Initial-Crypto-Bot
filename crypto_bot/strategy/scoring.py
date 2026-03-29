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


def score_indicators(regime, indicators, range_pos):
    normalized = _normalize_regime(regime)

    # Hard blocks for non-entry or downside regimes in long-only flow.
    if normalized in {"trend_down", "breakout_down", "choppy", "unknown"}:
        return 0.0

    if range_pos > 0.30 and normalized in {"range", "low_vol"}:
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
