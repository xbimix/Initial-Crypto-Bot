from analysis.indicators import (
    calculate_rsi,
    moving_average,
    calculate_volatility,
    market_regime
)
from utils.logger import setup_logger

logger = setup_logger()


def evaluate_symbol(symbol, ohlcv, cfg):
    """
    Evaluates a symbol and returns a fully scored decision.
    """

    closes = ohlcv["close"]
    price = closes[-1]

    # =========================
    # INDICATORS
    # =========================
    rsi = calculate_rsi(closes, period=14)
    ma20 = moving_average(closes, 20)
    ma50 = moving_average(closes, 50)
    ma200 = moving_average(closes, 200)
    vol = calculate_volatility(closes)

    if rsi is None or ma20 is None or ma50 is None:
        logger.info(f"⚠️ {symbol} insufficient data")
        return _hold(symbol, price, rsi, vol, "INSUFFICIENT_DATA")

    # =========================
    # REGIME FILTER (NEW)
    # =========================
    regime = market_regime(closes)

    if regime == "HIGH_VOL":
        logger.info(f"🚫 {symbol} skipped — HIGH VOLATILITY")
        return _hold(symbol, price, rsi, vol, regime)

    # =========================
    # TREND DETECTION
    # =========================
    trend = "NEUTRAL"
    if ma20 > ma50 and (ma200 is None or ma50 > ma200):
        trend = "BULL"
    elif ma20 < ma50 and (ma200 is None or ma50 < ma200):
        trend = "BEAR"

    # =========================
    # SCORING
    # =========================
    score = 0

    # RSI mean reversion
    if rsi < 30:
        score += 40
    elif rsi < 40:
        score += 20
    elif rsi > 70:
        score -= 40
    elif rsi > 60:
        score -= 20

    # Trend alignment
    if trend == "BULL" and price > ma20:
        score += 20
    elif trend == "BEAR" and price < ma20:
        score -= 20

    # Regime constraint: no mean reversion in strong trend
    if regime == "TREND" and rsi < 30:
        logger.info(f"🚫 {symbol} blocked — TREND regime")
        return _hold(symbol, price, rsi, vol, regime)

    # =========================
    # DECISION
    # =========================
    buy_threshold = cfg["strategy"]["buy_score"]
    sell_threshold = cfg["strategy"]["sell_score"]

    if score >= buy_threshold:
        action = "BUY"
    elif score <= -sell_threshold:
        action = "SELL"
    else:
        action = "HOLD"

    decision = {
        "symbol": symbol,
        "action": action,
        "score": score,
        "price": price,
        "rsi": rsi,
        "trend": trend,
        "regime": regime,
        "volatility": vol
    }

    logger.info(f"🧠 STRATEGY → {decision}")
    return decision


def _hold(symbol, price, rsi, vol, regime):
    """
    Standard HOLD decision
    """
    return {
        "symbol": symbol,
        "action": "HOLD",
        "score": 0,
        "price": price,
        "rsi": rsi,
        "trend": "UNKNOWN",
        "regime": regime,
        "volatility": vol
    }
