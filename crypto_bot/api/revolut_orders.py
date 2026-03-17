from api.revolut_api import _get
from utils.logger import setup_logger

logger = setup_logger("revolut_orders")


def get_active_orders():
    return _get("/orders", auth=True)
