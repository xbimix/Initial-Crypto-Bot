import time
import json
import requests
from pathlib import Path
from utils.logger import setup_logger

logger = setup_logger()

# =========================
# CONFIG
# =========================

BASE_URL = "https://revx.revolut.com/api/1.0"
API_KEY = Path("revolut-keys/api_key.txt").read_text().strip()

HEADERS = {
    "Accept": "application/json",
    "X-Revx-API-Key": API_KEY
}

TIMEOUT = 10


# =========================
# HELPERS
# =========================

def _get(path, params=None):
    url = f"{BASE_URL}{path}"
    r = requests.get(url, headers=HEADERS, params=params, timeout=TIMEOUT)
    r.raise_for_status()
    return r.json()


def _post(path, payload=None):
    url = f"{BASE_URL}{path}"
    r = requests.post(
        url,
        headers={**HEADERS, "Content-Type": "application/json"},
        data=json.dumps(payload or {}),
        timeout=TIMEOUT
    )
    r.raise_for_status()
    return r.json()


def _delete(path):
    url = f"{BASE_URL}{path}"
    r = requests.delete(url, headers=HEADERS, timeout=TIMEOUT)
    r.raise_for_status()
    return r.json()


# =========================
# CONFIGURATION
# =========================

def get_all_currencies():
    """
    Revolut-supported currencies + precision
    """
    logger.info("📘 Fetching currency configuration")
    return _get("/configuration/currencies")


def get_all_pairs():
    logger.info("📘 Fetching trading pairs")
    return _get("/configuration/pairs")


# =========================
# MARKET DATA
# =========================

def get_candles(symbol, interval="15m", limit=100):
    """
    OHLCV candles
    """
    logger.info(f"📊 Fetching candles {symbol} {interval}")
    return _get(
        "/market-data/candles",
        params={
            "symbol": symbol,
            "interval": interval,
            "limit": limit
        }
    )


def get_order_book(symbol, depth=20):
    """
    Public order book snapshot
    """
    logger.info(f"📚 Fetching order book {symbol}")
    return _get(
        "/market-data/order-book",
        params={
            "symbol": symbol,
            "limit": depth
        }
    )


def get_public_trades(symbol, limit=50):
    logger.info(f"🧾 Fetching public trades {symbol}")
    return _get(
        "/market-data/trades",
        params={
            "symbol": symbol,
            "limit": limit
        }
    )


# =========================
# ACCOUNT
# =========================

def get_balances():
    logger.info("💰 Fetching balances")
    return _get("/balances")


def get_active_orders():
    logger.info("📦 Fetching active orders")
    return _get("/orders")


def get_order(order_id):
    return _get(f"/orders/{order_id}")


def cancel_order(order_id):
    logger.info(f"❌ Cancelling order {order_id}")
    return _delete(f"/orders/{order_id}")


# =========================
# EXECUTION (LIVE — NOT USED YET)
# =========================

def place_order(symbol, side, quantity, order_type="market", price=None):
    """
    LIVE ORDER — gated by execution_mode
    """
    payload = {
        "symbol": symbol,
        "side": side,
        "type": order_type,
        "quantity": quantity
    }

    if price:
        payload["price"] = price

    logger.warning(f"⚠️ LIVE ORDER ATTEMPT: {payload}")
    return _post("/orders", payload)
