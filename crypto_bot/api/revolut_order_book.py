from api.revolut_api import _get
from utils.logger import setup_logger

logger = setup_logger("revolut_order_book")


def get_order_book(symbol: str) -> dict:
    """
    Fetch the raw order book payload for one trading pair.
    The response shape is expected to be:
    {
      "data": {"asks": [...], "bids": [...]},
      "metadata": {...}
    }
    """
    # High-frequency healthy event; keep available at DEBUG to reduce log churn.
    logger.debug(f"Fetching order book {symbol}")
    return _get(f"/public/order-book/{symbol}")
