from config import (
    BUY_SCORE_THRESHOLD,
    USE_TREND_FILTER,
    USE_VOLATILITY_FILTER,
    MAX_VOLATILITY_PERCENT,
    RSI_PERIOD,
    MA_WINDOWS
)

from analysis.indicators import (
    moving_average,
    calculate_volatility
)

from analysis.data_analysis import (
    calculate_support_resistance,
    calculate_rsi,
    detect_wave_pattern,
    calculate_fib_levels
)


def generate_signal(ohlcv):
    """
    Core strategy engine.
    Takes OHLCV data and returns a scored trading signal.
    DOES NOT execute trades.
    """

    closes = [c["close"] for c in ohlcv]
    highs = [c["high"] for c in ohlcv]
    lows = [c["low"] for c in ohlcv]

    current_price = closes[-1]

    # =========================
    # Indicator calculations
    # =========================

    support, resistance = calculate_support_resistance(closes)
    rsi_series = calculate_rsi(closes, RSI_PERIOD)
    rsi = rsi_series.iloc[-1] if hasattr(rsi_series, "iloc") else rsi_series

    ma_20 = moving_average(closes, MA_WINDOWS[0])
    ma_50 = moving_average(closes, MA_WINDOWS[1])
    ma_200 = moving_average(closes, MA_WINDOWS[2])

    volatility = calculate_volatility(closes)
    waves = detect_wave_pattern(closes)
    fib_levels = calculate_fib_levels(max(highs), min(lows))

    # =========================
    # Signal scoring
    # =========================

    score = 0
    reasons = []

    # ---- RSI (mean reversion core) ----
    if rsi is not None:
        if rsi < 30:
            score += 30
            reasons.append("RSI oversold")
        elif rsi > 70:
            score -= 25
            reasons.append("RSI overbought")

    # ---- Support proximity ----
    if support and current_price <= support * 1.02:
        score += 25
        reasons.append("Near support")

    # ---- Trend filter ----
    trend = "neutral"
    if USE_TREND_FILTER and ma_50 and ma_200:
        if ma_50 > ma_200:
            trend = "up"
            score += 20
            reasons.append("Macro uptrend")
        else:
            trend = "down"
            score -= 20
            reasons.append("Macro downtrend")

    # ---- Momentum ----
    if ma_20 and ma_50 and ma_20 > ma_50:
        score += 15
        reasons.append("Short-term momentum")

    # ---- Wave structure ----
    if waves["troughs"] and waves["troughs"][-1] > waves["peaks"][-1] if waves["peaks"] else False:
        score += 10
        reasons.append("Wave structure bullish")

    # ---- Fibonacci confluence ----
    fib_618 = fib_levels.get("0.618")
    if fib_618 and abs(current_price - fib_618) / fib_618 < 0.01:
        score += 10
        reasons.append("Fib 0.618 confluence")

    # ---- Volatility filter ----
    if USE_VOLATILITY_FILTER and volatility > MAX_VOLATILITY_PERCENT:
        score -= 35
        reasons.append("Excessive volatility")

    # =========================
    # Score normalization
    # =========================

    score = max(0, min(100, score))

    # =========================
    # Final signal object
    # =========================

    return {
        "symbol": None,  # injected by caller if needed
        "score": score,
        "action": "BUY" if score >= BUY_SCORE_THRESHOLD else "HOLD",
        "price": current_price,
        "support": support,
        "resistance": resistance,
        "trend": trend,
        "volatility": round(volatility, 4),
        "rsi": round(rsi, 2) if rsi else None,
        "reasons": reasons,
        "fib_levels": fib_levels
    }
