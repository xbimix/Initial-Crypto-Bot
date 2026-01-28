def detect_regime(trend_strength, volatility):
    if trend_strength > 0.6 and volatility < 3.0:
        return "trend"
    if volatility < 1.5:
        return "range"
    return "chop"
