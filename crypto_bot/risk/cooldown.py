def adaptive_cooldown(base, volatility):
    return int(base * (1 + volatility / 5))
