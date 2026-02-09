def detect_regime(momentum_norm, volatility, range_pos):
    """
    Regime detection for unstable / bear market conditions
    """

    # Strong negative momentum → dump zone
    if momentum_norm < -0.6:
        return "dump"

    # Violent move with high volatility → spike (do not chase)
    if volatility > 0.03 and range_pos > 0.35:
        return "spike"

    # Price near lows with stabilizing momentum → accumulation
    if range_pos <= 0.30 and momentum_norm > -0.2:
        return "accumulation"

    # Everything else → chop / no trade
    return "chop"



# def detect_regime(trend_strength, volatility):
#     if trend_strength > 0.6 and volatility < 3.0:
#         return "trend"
#     if volatility < 1.5:
#         return "range"
#     return "chop"
