from api.revolut_trades import get_last_trades
from api.revolut_order_book import get_order_book
from utils.logger import setup_logger
logger = setup_logger("market_data")

def fetch_market_snapshot(symbol: str, cfg: dict) -> dict | None:
    """
    Revolut-first market snapshot.
    Uses LAST TRADES only (no candles, no OHLC assumptions).
    Safe for paper trading and public-data-only mode.
    """

    try:
        logger.info("📘 Fetching last trades from Revolut")

        # Revolut trades are asset-based (BTC, ETH), not pair-based
        asset = symbol.split("-")[0]

        trades = get_last_trades(limit=cfg.get("lookback", 100))

        # Filter trades for the asset we care about
        trades = [t for t in trades if t.get("aid") == asset]

        if not trades:
            logger.warning(f"No trades for {symbol}")
            return None

        prices = [float(t["p"]) for t in trades]

        last_price = prices[0]
        first_price = prices[-1]

        momentum = (
            (last_price - first_price) / first_price
            if first_price > 0
            else 0.0
        )

        snapshot = {
            "symbol": symbol,
            "price": last_price,
            "mid_price": last_price,
            "spread": None,          # Order book intentionally skipped
            "momentum": momentum,
            "prices": prices,
            "trade_count": len(prices),
        }

        logger.info(
            f"SNAPSHOT {symbol} | "
            f"price={last_price:.2f} "
            f"momentum={momentum:.5f} "
            f"trades={len(prices)}"
        )

        return snapshot

    except Exception as e:
        logger.exception(f"Market snapshot error for {symbol}: {e}")
        return None

# from api.revolut_trades import get_last_trades
# from api.revolut_order_book import get_order_book
# from utils.logger import setup_logger
# logger = setup_logger("market_data")
# def fetch_market_snapshot(symbol: str, cfg: dict) -> dict | None:
#     """
#     Revolut-first market snapshot.
#     Uses:
#     - public last trades (filtered client-side)
#     - public order book
#     No candles. No OHLC assumptions.
#     """

#     try:
#         base_asset = symbol.split("-")[0]  # BTC-USDT -> BTC
#         lookback = cfg.get("lookback", 100)

#         # --- Trades (Revolut has NO symbol filter at API level)
#         all_trades = get_last_trades(limit=lookback)
#         trades = [t for t in all_trades if t.get("aid") == base_asset]

#         if not trades:
#             logger.warning(f"No trades for {symbol}")
#             return None

#         prices = [float(t["p"]) for t in trades]
#         last_price = prices[0]

#         # Simple momentum (recent vs oldest)
#         momentum = (prices[0] - prices[-1]) / prices[-1]

#         # --- Order book (symbol IS required here)
#         rev_symbol = symbol.replace("USDT", "USD")
#         book = get_order_book(rev_symbol)
        
#         if not book or not book.get("bids") or not book.get("asks"):
#             logger.warning(f"No order book for {symbol}")
#             return None

#         best_bid = float(book["bids"][0]["p"])
#         best_ask = float(book["asks"][0]["p"])
#         spread = best_ask - best_bid
#         mid_price = (best_bid + best_ask) / 2

#         snapshot = {
#             "symbol": symbol,
#             "price": last_price,
#             "mid_price": mid_price,
#             "spread": spread,
#             "momentum": momentum,
#             "prices": prices,
#             "trade_count": len(trades),
#         }

#         logger.info(
#             f"SNAPSHOT {symbol} | "
#             f"price={last_price:.2f} "
#             f"spread={spread:.4f} "
#             f"momentum={momentum:.5f} "
#             f"trades={len(trades)}"
#         )

#         return snapshot

#     except Exception as e:
#         logger.exception(f"Market snapshot error for {symbol}: {e}")
#         return None


# from collections import defaultdict
# from datetime import datetime, timedelta
# from api.revolut_trades import get_last_trades
# from utils.logger import logger

# def _bucket_time(ts: datetime, minutes: int) -> datetime:
#     discard = timedelta(
#         minutes=ts.minute % minutes,
#         seconds=ts.second,
#         microseconds=ts.microsecond,
#     )
#     return ts - discard

# def fetch_ohlcv(symbol: str, timeframe_minutes: int = 15, limit: int = 100):
#     """
#     Build OHLCV candles from Revolut last trades.
#     """
#     trades = get_last_trades(limit=limit)
#     if not trades:
#         logger.warning("⚠️ No trades received")
#         return []

#     buckets = defaultdict(list)

#     for t in trades:
#         if t["aid"] != symbol.split("-")[0]:
#             continue

#         price = float(t["p"])
#         qty = float(t["q"])
#         ts = datetime.fromisoformat(t["tdt"].replace("Z", "+00:00"))

#         bucket = _bucket_time(ts, timeframe_minutes)
#         buckets[bucket].append((price, qty))

#     candles = []

#     for ts in sorted(buckets.keys()):
#         prices = [p for p, _ in buckets[ts]]
#         volume = sum(q for _, q in buckets[ts])

#         candles.append({
#             "timestamp": ts,
#             "open": prices[0],
#             "high": max(prices),
#             "low": min(prices),
#             "close": prices[-1],
#             "volume": volume,
#         })

#     logger.info(f"📊 Built {len(candles)} candles for {symbol}")
#     return candles
