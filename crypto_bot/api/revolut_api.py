import json
import requests
from pathlib import Path
from utils.logger import setup_logger

logger = setup_logger()

# ======================================================
# AUTH
# ======================================================

BASE_DIR = Path(__file__).resolve().parents[2]
KEY_PATH = BASE_DIR / "revolut-keys" / "api_key.txt"

if not KEY_PATH.exists():
    raise FileNotFoundError(f"Missing API key: {KEY_PATH}")

API_KEY = KEY_PATH.read_text().strip()

BASE_URL = "https://revx.revolut.com/api/1.0"

HEADERS = {
    "Accept": "application/json",
    "X-Revx-API-Key": API_KEY,
}

TIMEOUT = 10

# ======================================================
# INTERNAL
# ======================================================

def _get(path, params=None):
    r = requests.get(
        f"{BASE_URL}{path}",
        headers=HEADERS,
        params=params,
        timeout=TIMEOUT
    )
    r.raise_for_status()
    return r.json()

# ======================================================
# GRANULARITY
# ======================================================

GRANULARITY_MAP = {
    "1m": "ONE_MIN",
    "5m": "FIVE_MIN",
    "15m": "FIFTEEN_MIN",
    "30m": "THIRTY_MIN",
    "1h": "ONE_HOUR",
    "4h": "FOUR_HOUR",
    "1d": "ONE_DAY",
}

# ======================================================
# SYMBOL NORMALIZATION (FINAL)
# ======================================================

SUPPORTED_SYMBOLS = {
    "BTC-USDT": "BTC-USD",
    "ETH-USDT": "ETH-USD",
    "SOL-USDT": "SOL-USD",
}

def normalize_symbol(symbol: str) -> str:
    if symbol not in SUPPORTED_SYMBOLS:
        raise ValueError(f"Unsupported Revolut symbol: {symbol}")
    return SUPPORTED_SYMBOLS[symbol]

# ======================================================
# MARKET DATA (FINAL)
# ======================================================

def get_candles(symbol, interval="15m", limit=100):
    if interval not in GRANULARITY_MAP:
        raise ValueError(f"Unsupported interval: {interval}")

    revolut_symbol = normalize_symbol(symbol)

    logger.info(
        f"📊 Fetching candles {revolut_symbol} ({GRANULARITY_MAP[interval]})"
    )

    return _get(
        "/market-data/candles",
        params={
            "symbol": revolut_symbol,
            "granularity": GRANULARITY_MAP[interval],
            "limit": limit
        }
    )
