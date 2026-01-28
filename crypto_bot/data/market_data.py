# import requests
# import time
# from typing import List, Dict

# REVOLUTX_BASE_URL = "https://api.revolut.com/api/1.0"

# # Map human timeframes to seconds (RevolutX-safe abstraction)
# TIMEFRAME_SECONDS = {
#     "1m": 60,
#     "5m": 300,
#     "15m": 900,
#     "30m": 1800,
#     "1h": 3600
# }


# def fetch_ohlcv(
#     symbol: str,
#     timeframe: str = "15m",
#     limit: int = 100
# ) -> List[Dict]:
#     """
#     Fetch OHLCV data for a symbol from RevolutX (spot, read-only).

#     Returns a list of dicts with:
#     timestamp, open, high, low, close, volume
#     """

#     if timeframe not in TIMEFRAME_SECONDS:
#         raise ValueError(f"Unsupported timeframe: {timeframe}")

#     endpoint = f"{REVOLUTX_BASE_URL}/public/market-data"
#     params = {
#         "symbol": symbol,
#         "granularity": TIMEFRAME_SECONDS[timeframe],
#         "limit": limit
#     }

#     try:
#         response = requests.get(endpoint, params=params, timeout=10)
#         response.raise_for_status()
#         payload = response.json()
#     except Exception as e:
#         raise RuntimeError(f"Failed to fetch market data: {e}")

#     # Defensive parsing
#     candles = payload.get("data") or payload.get("candles")
#     if not candles:
#         raise RuntimeError("No candle data returned from RevolutX")

#     ohlcv = []

#     for c in candles:
#         try:
#             ohlcv.append({
#                 "timestamp": int(c["timestamp"]),
#                 "open": float(c["open"]),
#                 "high": float(c["high"]),
#                 "low": float(c["low"]),
#                 "close": float(c["close"]),
#                 "volume": float(c.get("volume", 0))
#             })
#         except (KeyError, ValueError):
#             # Skip malformed candles safely
#             continue

#     if len(ohlcv) < 20:
#         raise RuntimeError("Insufficient candle data for strategy")

#     return ohlcv
"""
Market data adapter
- Uses Binance public API for paper trading
- Accepts BTC/USDT, BTC-USD, BTCUSDT
- Always converts to BTCUSDT internally
"""

import requests

BINANCE_URL = "https://api.binance.com/api/v3/klines"


def fetch_ohlcv(symbol: str, interval: str = "15m", limit: int = 100):
    """
    Fetch OHLCV candles from Binance.
    Returns list of dicts: open, high, low, close, volume
    """

    symbol = symbol.replace("/", "").replace("-", "").upper()

    params = {
        "symbol": symbol,
        "interval": interval,
        "limit": limit,
    }

    res = requests.get(BINANCE_URL, params=params, timeout=10)
    res.raise_for_status()

    candles = res.json()

    return [
        {
            "open": float(c[1]),
            "high": float(c[2]),
            "low": float(c[3]),
            "close": float(c[4]),
            "volume": float(c[5]),
        }
        for c in candles
    ]
