from api.revolut_api import get_candles
from utils.logger import setup_logger

logger = setup_logger()


def fetch_ohlcv(symbol, interval="15m", limit=100):
    """
    Fetch and normalize OHLCV candles from Revolut X.

    Returns:
        {
            "timestamps": [...],
            "open": [...],
            "high": [...],
            "low": [...],
            "close": [...],
            "volume": [...]
        }
    """
    try:
        raw = get_candles(symbol, interval, limit)

        if not raw or "candles" not in raw:
            logger.warning(f"⚠️ No candle data for {symbol}")
            return None

        timestamps = []
        open_ = []
        high = []
        low = []
        close = []
        volume = []

        for c in raw["candles"]:
            timestamps.append(int(c["timestamp"]))
            open_.append(float(c["open"]))
            high.append(float(c["high"]))
            low.append(float(c["low"]))
            close.append(float(c["close"]))
            volume.append(float(c.get("volume", 0)))

        logger.info(
            f"📊 OHLCV normalized for {symbol} ({len(close)} candles)"
        )

        return {
            "timestamps": timestamps,
            "open": open_,
            "high": high,
            "low": low,
            "close": close,
            "volume": volume
        }

    except Exception as e:
        logger.exception(f"🔥 Market data error for {symbol}: {e}")
        return None
