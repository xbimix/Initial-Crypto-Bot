from api.revolut_api import _get
from utils.logger import setup_logger

logger = setup_logger("revolut_trades")

def get_last_trades(limit: int = 100):
    """
    Fetch latest public trades from Revolut X.
    Returns raw trade list.
    """
    logger.info("📘 Fetching last trades from Revolut")
    data = _get("/public/last-trades")
    return data.get("data", [])[:limit]
