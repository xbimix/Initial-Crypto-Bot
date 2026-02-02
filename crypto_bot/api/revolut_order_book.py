from api.revolut_api import _get
from utils.logger import setup_logger
logger = setup_logger("revolut_order_book")



def get_order_book(symbol: str):
    """
    symbol example: BTC-USD
    """
    logger.info(f"📘 Fetching order book {symbol}")
    return _get(f"/public/order-book/{symbol}")
