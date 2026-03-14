import time

from api.revolut_api import _get
from utils.logger import setup_logger

logger = setup_logger("revolut_trades")
LAST_TRADES_CACHE_TTL = 5.0
_LAST_TRADES_CACHE = {
    "ts": 0.0,
    "limit": 0,
    "data": [],
}


def get_last_trades(symbol: str | None = None, limit: int = 50):
    """
    Fetch the global public trade tape from Revolut X.
    Symbol filtering must be done client-side because the endpoint returns the latest
    exchange trades across instruments.
    """

    label = symbol or "all symbols"
    now = time.time()

    if (
        _LAST_TRADES_CACHE["data"]
        and (now - _LAST_TRADES_CACHE["ts"]) <= LAST_TRADES_CACHE_TTL
        and _LAST_TRADES_CACHE["limit"] >= limit
    ):
        return _LAST_TRADES_CACHE["data"][:limit]

    # Healthy periodic refresh; keep at DEBUG to reduce normal-mode log volume.
    logger.debug(f"Refreshing global last trades from Revolut for {label}")

    try:
        data = _get(
            "/public/last-trades",
            params={
                "limit": limit,
            },
        )

        trades = data.get("data", [])

        if not isinstance(trades, list):
            logger.warning(f"Unexpected trade payload for {label}: {data}")
            return []

        _LAST_TRADES_CACHE["ts"] = now
        _LAST_TRADES_CACHE["limit"] = limit
        _LAST_TRADES_CACHE["data"] = trades

        return trades

    except Exception as e:
        logger.exception(f"Failed to fetch trades for {label}: {e}")
        if _LAST_TRADES_CACHE["data"]:
            logger.warning("Using stale cached global last trades after refresh failure")
            return _LAST_TRADES_CACHE["data"][:limit]
        return []
