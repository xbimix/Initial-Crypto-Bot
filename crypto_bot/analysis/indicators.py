import math
from utils.logger import setup_logger

logger = setup_logger()


# =========================
# RSI
# =========================

def calculate_rsi(closes, period=14):
    """
    Standard RSI calculation (Wilder's method).
    Returns latest RSI value or None.
    """
    if len(closes) < period + 1:
        return None

    gains = []
    losses = []

    for i in range(1, period + 1):
        delta = closes[-i] - closes[-i - 1]
        if delta >= 0:
            gains.append(delta)
            losses.append(0)
        else:
            gains.append(0)
            losses.append(abs(delta))

    avg_gain = sum(gains) / period
    avg_loss = sum(losses) / period

    if avg_loss == 0:
        return 100.0

    rs = avg_gain / avg_loss
    rsi = 100 - (100 / (1 + rs))

    return round(rsi, 2)


# =========================
# MOVING AVERAGE
# =========================

def moving_average(values, window):
    """
    Simple Moving Average (SMA).
    Returns latest MA value or None.
    """
    if len(values) < window:
        return None

    return sum(values[-window:]) / window


# =========================
# VOLATILITY
# =========================

def calculate_volatility(closes, window=20):
    """
    Standard deviation of log returns.
    Returns volatility as percentage.
    """
    if len(closes) < window + 1:
        return None

    returns = []
    for i in range(-window, 0):
        r = math.log(closes[i] / closes[i - 1])
        returns.append(r)

    mean = sum(returns) / window
    variance = sum((r - mean) ** 2 for r in returns) / window
    std = math.sqrt(variance)

    return round(std * 100, 4)
