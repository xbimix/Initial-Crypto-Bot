from pathlib import Path
from utils.logger import setup_logger
logger = setup_logger("revolut_auth")




API_KEY_PATH = Path("revolut-keys/api_key.txt")

def get_api_key() -> str:
    if not API_KEY_PATH.exists():
        raise RuntimeError("API key file not found (revolut-keys/api_key.txt)")
    return API_KEY_PATH.read_text().strip()
