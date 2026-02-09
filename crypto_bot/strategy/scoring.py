def score_indicators(regime, indicators, range_pos):
    # HARD BLOCK — your core rule
    if range_pos > 0.30:
        return 0.0

    score = 0.0

    # RSI mean-reversion bias
    if indicators["rsi"] < 35:
        score += 40
    elif indicators["rsi"] < 45:
        score += 20

    # Momentum confirmation (not dominance)
    if indicators["momentum"] > -0.2:
        score += 20

    # Structure support
    if indicators.get("structure", 0) > 0:
        score += 20

    # Regime modifier (small effect)
    if regime == "accumulation":
        score += 20
    elif regime in ("dump", "spike"):
        score -= 30

    return max(0, min(score, 100))


# def score_indicators(regime, indicators):
#     weights = {
#         "trend": {
#             "rsi": 0.2,
#             "ma": 0.5,
#             "vol": 0.1,
#             "structure": 0.2,
#         },
#         "range": {
#             "rsi": 0.5,
#             "ma": 0.2,
#             "vol": 0.2,
#             "structure": 0.1,
#         },
#         "chop": {
#             "rsi": 0.2,
#             "ma": 0.2,
#             "vol": 0.4,
#             "structure": 0.2,
#         },
#     }

#     w = weights[regime]

#     score = (
#         indicators["rsi"] * w["rsi"]
#         + indicators["ma"] * w["ma"]
#         + indicators["vol"] * w["vol"]
#         + indicators["structure"] * w["structure"]
#     )

#     return round(score, 2)
