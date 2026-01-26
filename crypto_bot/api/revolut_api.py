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

BASE_URL = "https://api.revolut.com/api/1.0"

API_KEY = os.getenv("REVOLUT_API_KEY")
PRIVATE_KEY_PATH = os.getenv("REVOLUT_PRIVATE_KEY_PATH")


def _load_signing_key():
    pem_data = Path(PRIVATE_KEY_PATH).read_bytes()
    private_key = serialization.load_pem_private_key(pem_data, password=None)
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


def get_balances():
    path = "/balances"
    headers = _sign("GET", path)
    return requests.get(BASE_URL + path, headers=headers).json()


def get_active_orders():
    path = "/orders/active"
    headers = _sign("GET", path)
    return requests.get(BASE_URL + path, headers=headers).json()


def place_order(symbol, side, size, price=None):
    path = "/orders"
    order_type = "market" if price is None else "limit"

    body = {
        "symbol": symbol,
        "side": side,
        "order_configuration": {
            order_type: {
                "base_size": str(size),
                **({ "price": str(price) } if price else {})
            }
        }
    }

    body_str = json.dumps(body, separators=(",", ":"))
    headers = _sign("POST", path, body=body_str)

    return requests.post(
        BASE_URL + path,
        headers=headers,
        data=body_str
    ).json()


def cancel_order(order_id):
    path = f"/orders/{order_id}"
    headers = _sign("DELETE", path)
    return requests.delete(BASE_URL + path, headers=headers).json()
