def clamp(val, low=0, high=100):
    return max(low, min(high, val))

def normalize_rsi(rsi):
    return clamp(100 - abs(50 - rsi) * 2)

def normalize_ma(price, ma):
    return clamp((price / ma) * 50)

def normalize_volatility(vol):
    return clamp(100 - vol * 10)
