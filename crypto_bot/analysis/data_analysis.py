import numpy as np
import pandas as pd


# =====================================================
# SUPPORT & RESISTANCE
# =====================================================

def calculate_support_resistance(prices, window=14):
    """
    Dynamic support/resistance using recent volatility bands.
    Safe for flat and low-volatility markets.
    """
    prices = np.array(prices, dtype=float)

    if len(prices) < window:
        return float(np.min(prices)), float(np.max(prices))

    recent = prices[-window:]
    std = np.std(recent)

    # Flat market protection
    if std < 1e-6:
        return float(np.min(recent)), float(np.max(recent))

    mean = np.mean(recent)
    support = mean - 2 * std
    resistance = mean + 2 * std

    return round(float(support), 6), round(float(resistance), 6)


# =====================================================
# RSI
# =====================================================

def calculate_rsi(prices, period=14):
    """
    RSI with numerical stability.
    Returns Pandas Series (standard practice).
    """
    prices = pd.Series(prices, dtype=float)

    delta = prices.diff()
    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)

    avg_gain = gain.rolling(period, min_periods=period).mean()
    avg_loss = loss.rolling(period, min_periods=period).mean()

    rs = avg_gain / (avg_loss + 1e-9)
    rsi = 100 - (100 / (1 + rs))

    return rsi


# =====================================================
# WAVE PATTERN (PEAK / TROUGH)
# =====================================================

def detect_wave_pattern(prices, sensitivity=3):
    """
    Lightweight peak/trough detection.
    Used only as a CONFIRMATION signal.
    """
    prices = np.array(prices, dtype=float)

    peaks = []
    troughs = []

    for i in range(sensitivity, len(prices) - sensitivity):
        window = prices[i - sensitivity:i + sensitivity + 1]

        if prices[i] == np.max(window):
            peaks.append(i)
        elif prices[i] == np.min(window):
            troughs.append(i)

    return {
        "peaks": peaks,
        "troughs": troughs
    }


# =====================================================
# MOVING AVERAGES (DATAFRAME UTILITY)
# =====================================================

def calculate_moving_averages(ohlcv, windows=(20, 50, 200)):
    """
    Adds moving averages to OHLCV dataframe.
    Used for diagnostics / backtesting (optional).
    """
    df = pd.DataFrame(
        ohlcv,
        columns=["timestamp", "open", "high", "low", "close", "volume"]
    )

    for w in windows:
        df[f"ma_{w}"] = df["close"].rolling(w, min_periods=w).mean()

    return df


# =====================================================
# FIBONACCI LEVELS
# =====================================================

def calculate_fib_levels(high, low):
    """
    Fibonacci retracement levels.
    """
    high = float(high)
    low = float(low)

    diff = high - low
    if diff <= 0:
        return {}

    return {
        "0.0": high,
        "0.236": high - diff * 0.236,
        "0.382": high - diff * 0.382,
        "0.5": high - diff * 0.5,
        "0.618": high - diff * 0.618,
        "1.0": low
    }


# =====================================================
# AUTO-REBUY LEVELS (RISK UTILITY)
# =====================================================

def auto_rebuy_price(current_price, risk_percent=2.0, rebuy_count=2):
    """
    Generates staggered rebuy levels.
    Pure math — exchange agnostic.
    """
    current_price = float(current_price)

    levels = []
    price = current_price

    for _ in range(rebuy_count):
        price *= (1 - risk_percent / 100)
        levels.append(round(price, 6))

    return levels
##final