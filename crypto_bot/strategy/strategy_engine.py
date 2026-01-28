from analysis.indicators import (
    moving_average,
    calculate_volatility,
)

from analysis.data_analysis import (
    calculate_support_resistance,
    calculate_rsi,
    detect_wave_pattern,
    calculate_fib_levels,
)


def generate_signal(ohlcv, cfg):
    """
    Core strategy engine.
    Deterministic, explainable, executor-safe.
    """

    # =========================
    # PRICE SERIES
    # =========================
    closes = [c["close"] for c in ohlcv]
    highs = [c["high"] for c in ohlcv]
    lows = [c["low"] for c in ohlcv]

    current_price = closes[-1]

    # =========================
    # CONFIG
    # =========================
    BUY_SCORE_THRESHOLD = cfg["strategy"]["buy_score_threshold"]

    USE_TREND_FILTER = cfg["filters"]["trend"]
    USE_VOLATILITY_FILTER = cfg["filters"]["volatility"]
    MAX_VOLATILITY_PERCENT = cfg["filters"]["max_volatility_percent"]

    RSI_PERIOD = cfg["indicators"]["rsi_period"]
    MA_WINDOWS = cfg["indicators"]["ma_windows"]

    # =========================
    # INDICATORS
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
    # REGIME DETECTION
    # =========================
    trend_strength = 0
    if ma_50 and ma_200:
        trend_strength = abs(ma_50 - ma_200) / ma_200

    if trend_strength > 0.01 and volatility < MAX_VOLATILITY_PERCENT:
        regime = "trend"
    elif volatility < MAX_VOLATILITY_PERCENT * 0.6:
        regime = "range"
    else:
        regime = "chop"

    # =========================
    # SCORING
    # =========================
    score = 0
    reasons = []

    # --- RSI ---
    if rsi is not None:
        if rsi < 30:
            score += 30
            reasons.append("RSI oversold")
        elif rsi > 70:
            score -= 25
            reasons.append("RSI overbought")

    # --- SUPPORT ---
    if support and current_price <= support * 1.02:
        score += 25
        reasons.append("Near support")

    # --- TREND ---
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

    # --- MOMENTUM ---
    if ma_20 and ma_50 and ma_20 > ma_50:
        score += 15
        reasons.append("Short-term momentum")

    # --- WAVE STRUCTURE ---
    if waves.get("troughs") and waves.get("peaks"):
        if waves["troughs"][-1] > waves["peaks"][-1]:
            score += 10
            reasons.append("Wave structure bullish")

    # --- FIB CONFLUENCE ---
    fib_618 = fib_levels.get("0.618")
    if fib_618 and abs(current_price - fib_618) / fib_618 < 0.01:
        score += 10
        reasons.append("Fib 0.618 confluence")

    # --- VOLATILITY FILTER ---
    if USE_VOLATILITY_FILTER and volatility > MAX_VOLATILITY_PERCENT:
        score -= 35
        reasons.append("Excessive volatility")

    # =========================
    # FINAL NORMALIZATION
    # =========================
    score = max(0, min(100, score))

    action = "BUY" if score >= BUY_SCORE_THRESHOLD and regime != "chop" else "HOLD"

    return {
        "action": action,
        "score": score,
        "price": current_price,
        "support": support,
        "resistance": resistance,
        "trend": trend,
        "regime": regime,
        "volatility": round(volatility, 4),
        "rsi": round(rsi, 2) if rsi is not None else None,
        "reasons": reasons,
    }
