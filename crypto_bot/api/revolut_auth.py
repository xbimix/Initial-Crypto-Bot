from utils.logger import setup_logger
from api.revolut_secrets import load_api_key

logger = setup_logger("revolut_auth")


def get_api_key() -> str:
    key, source = load_api_key(allow_missing=False)
    logger.debug(f"Loaded Revolut API key from {source}")
    assert key is not None
    return key
