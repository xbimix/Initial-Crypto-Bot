from api.revolut_api import _get
from api.revolut_auth import get_api_key
from utils.logger import setup_logger
logger = setup_logger("revolut_balances")
def get_balances():
    return _get(
        "/balances",
        headers={"X-Revx-API-Key": get_api_key()},
    )
