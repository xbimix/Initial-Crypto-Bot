def score_indicators(regime, indicators, range_pos):
    # Hard block above preferred range for mean-reversion entries.
    if range_pos > 0.30:
        return 0.0

    score = 0.0

    # RSI mean-reversion bias.
    if indicators["rsi"] < 35:
        score += 40
    elif indicators["rsi"] < 45:
        score += 20

    # Momentum confirmation (not dominance).
    if indicators["momentum"] > -0.2:
        score += 20

    # Structure support.
    if indicators.get("structure", 0) > 0:
        score += 20

    # Regime modifier (small effect).
    if regime == "accumulation":
        score += 20
    elif regime in ("dump", "spike"):
        score -= 30

    return max(0.0, min(score, 100.0))
