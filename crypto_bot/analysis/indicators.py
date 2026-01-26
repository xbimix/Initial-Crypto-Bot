import numpy as np

def moving_average(prices, window):
    if len(prices) < window:
        return None
    return sum(prices[-window:]) / window

def calculate_rsi(prices, period=14):
    if len(prices) < period + 1:
        return None

    gains, losses = [], []
    for i in range(1, period + 1):
        diff = prices[-i] - prices[-i - 1]
        if diff >= 0:
            gains.append(diff)
        else:
            losses.append(abs(diff))

    avg_gain = sum(gains) / period if gains else 0
    avg_loss = sum(losses) / period if losses else 1

    rs = avg_gain / avg_loss
    return 100 - (100 / (1 + rs))

def calculate_volatility(prices):
    returns = np.diff(prices) / prices[:-1]
    return np.std(returns) * 100

def auto_rebuy_prices(price, risk_percent, count):
    return [price * (1 - (risk_percent / 100) * i) for i in range(1, count + 1)]
