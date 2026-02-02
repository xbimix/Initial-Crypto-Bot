from api.revolut_api import _get
from api.revolut_auth import get_api_key
from utils.logger import setup_logger
logger = setup_logger("revolut_orders")


def get_active_orders():
    return _get(
        "/orders",
        headers={"X-Revx-API-Key": get_api_key()},
    )
