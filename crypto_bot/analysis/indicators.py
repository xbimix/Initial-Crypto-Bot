import math
from utils.logger import setup_logger

logger = setup_logger()

# =========================
# RSI
# =========================

def calculate_rsi(closes, period=14):
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
    if len(values) < window:
        return None
    return sum(values[-window:]) / window


# =========================
# VOLATILITY
# =========================

def calculate_volatility(closes, window=20):
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


# =========================
# MARKET REGIME (NEW)
# =========================

def market_regime(closes, fast=20, slow=50, vol_window=20):
    """
    Determines market regime:
    - TREND
    - RANGE
    - HIGH_VOL
    """

    ma_fast = moving_average(closes, fast)
    ma_slow = moving_average(closes, slow)
    vol = calculate_volatility(closes, vol_window)

    if ma_fast is None or ma_slow is None or vol is None:
        return "UNKNOWN"

    # High volatility = no trade
    if vol > 4.0:
        return "HIGH_VOL"

    # Trend strength via MA separation
    ma_diff_pct = abs(ma_fast - ma_slow) / ma_slow * 100

    if ma_diff_pct > 0.4:
        return "TREND"

    return "RANGE"
