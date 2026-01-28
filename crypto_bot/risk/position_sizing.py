def position_size(balance, confidence, max_risk=0.02):
    base = balance * max_risk
    return round(base * (confidence / 100), 4)
