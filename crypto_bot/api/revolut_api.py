import time
import json
import base64
import requests
import os
from pathlib import Path
from nacl.signing import SigningKey
from cryptography.hazmat.primitives import serialization
from dotenv import load_dotenv

load_dotenv()

# ---------------------------
# Paths (ABSOLUTE, SAFE)
# ---------------------------

PROJECT_ROOT = Path(__file__).resolve().parents[2]
KEYS_DIR = PROJECT_ROOT / "revolut-keys"

PRIVATE_KEY_PATH = KEYS_DIR / "private.pem"
PUBLIC_KEY_PATH = KEYS_DIR / "public.pem"

# ---------------------------
# API Config
# ---------------------------

BASE_URL = "https://api.revolut.com/api/1.0"
API_KEY = os.getenv("REVOLUT_API_KEY")

READ_ONLY = True  # 🔒 SAFE MODE (spot-view / no trades)


# ---------------------------
# Signing
# ---------------------------

def _load_signing_key():
    if not PRIVATE_KEY_PATH.exists():
        raise FileNotFoundError(f"Private key not found: {PRIVATE_KEY_PATH}")

    pem_data = PRIVATE_KEY_PATH.read_bytes()
    private_key = serialization.load_pem_private_key(
        pem_data,
        password=None
    )

    raw = private_key.private_bytes(
        encoding=serialization.Encoding.Raw,
        format=serialization.PrivateFormat.Raw,
        encryption_algorithm=serialization.NoEncryption()
    )

    return SigningKey(raw)



SIGNING_KEY = _load_signing_key()


def _sign(method, path, query="", body=""):
    timestamp = str(int(time.time() * 1000))
    message = f"{timestamp}{method}{path}{query}{body}".encode()

    signature = SIGNING_KEY.sign(message).signature

    return {
        "X-Revx-API-Key": API_KEY,
        "X-Revx-Timestamp": timestamp,
        "X-Revx-Signature": base64.b64encode(signature).decode(),
        "Content-Type": "application/json"
    }


# ---------------------------
# ---------------------------
# API Calls (Executor-facing)
# ---------------------------

def get_balances():
    """
    Fetch account balances (spot, safe).
    """
    path = "/balances"
    headers = _sign("GET", path)
    resp = requests.get(BASE_URL + path, headers=headers, timeout=10)
    resp.raise_for_status()
    return resp.json()


def get_active_orders():
    """
    Fetch active open orders.
    """
    path = "/orders/active"
    headers = _sign("GET", path)
    resp = requests.get(BASE_URL + path, headers=headers, timeout=10)
    resp.raise_for_status()
    return resp.json()


def place_order(symbol, side, size, price=None):
    """
    Place an order (DRY-RUN when READ_ONLY=True).
    """
    if READ_ONLY:
        print(f"[DRY-RUN] place_order blocked: {side} {symbol} size={size}")
        return None

    path = "/orders"
    order_type = "market" if price is None else "limit"

    body = {
        "symbol": symbol,
        "side": side,
        "order_configuration": {
            order_type: {
                "base_size": str(size),
                **({"price": str(price)} if price else {})
            }
        }
    }

    body_str = json.dumps(body, separators=(",", ":"))
    headers = _sign("POST", path, body=body_str)

    resp = requests.post(
        BASE_URL + path,
        headers=headers,
        data=body_str,
        timeout=10
    )
    resp.raise_for_status()
    return resp.json()


def cancel_order(order_id):
    """
    Cancel an order (DRY-RUN when READ_ONLY=True).
    """
    if READ_ONLY:
        print(f"[DRY-RUN] cancel_order blocked: {order_id}")
        return None

    path = f"/orders/{order_id}"
    headers = _sign("DELETE", path)
    resp = requests.delete(BASE_URL + path, headers=headers, timeout=10)
    resp.raise_for_status()
    return resp.json()
