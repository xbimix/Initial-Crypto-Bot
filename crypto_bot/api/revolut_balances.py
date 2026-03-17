from api.revolut_api import _get
from utils.logger import setup_logger

logger = setup_logger("revolut_balances")


def get_balances():
    return _get("/balances", auth=True)
