from api.revolut_api import _get
from utils.logger import setup_logger

logger = setup_logger("revolut_trades")


def get_last_trades(symbol: str, limit: int = 50):
    """
    Fetch latest public trades for a specific symbol from Revolut X.
    Returns raw trade list.
    """

    logger.info(f"📘 Fetching last trades from Revolut for {symbol}")

    try:
        data = _get(
            "/public/last-trades",
            params={
                "symbol": symbol,
                "limit": limit,
            },
        )

        trades = data.get("data", [])

        if not isinstance(trades, list):
            logger.warning(f"Unexpected trade payload for {symbol}: {data}")
            return []

        return trades

    except Exception as e:
        logger.exception(f"Failed to fetch trades for {symbol}: {e}")
        return []
