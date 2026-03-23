from __future__ import annotations

import base64
import json
import os
import time
from collections import deque
from functools import lru_cache
from urllib.parse import urlencode

import requests
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from api.revolut_secrets import load_api_key, resolve_private_key_path
from utils.logger import setup_logger

logger = setup_logger("revolut_api")

BASE_URL = "https://revx.revolut.com/api/1.0"
try:
    _PUBLIC_WINDOW_SECONDS_RAW = float(os.getenv("REVBOT_PUBLIC_WINDOW_SECONDS", "10"))
except (TypeError, ValueError):
    _PUBLIC_WINDOW_SECONDS_RAW = 10.0
PUBLIC_WINDOW_SECONDS = max(_PUBLIC_WINDOW_SECONDS_RAW, 1.0)
try:
    _PUBLIC_MAX_REQUESTS_RAW = int(float(os.getenv("REVBOT_PUBLIC_MAX_REQUESTS", "12")))
except (TypeError, ValueError):
    _PUBLIC_MAX_REQUESTS_RAW = 12
PUBLIC_MAX_REQUESTS = max(_PUBLIC_MAX_REQUESTS_RAW, 1)
PUBLIC_THROTTLE_PADDING = 0.05
RETRYABLE_STATUS_CODES = {429}
MAX_RETRIES = 1
REQUEST_TIMEOUT_SECONDS = 10
USER_AGENT = "RevBot/1.0 (+local)"
_PUBLIC_REQUEST_TIMES = deque()
_PUBLIC_RATE_LIMIT_TIMES = deque()
_PUBLIC_THROTTLE_EVENTS = deque()
_MISSING_AUTH_WARNED = False
_MISSING_SIGNING_WARNED = False
_HTTP_SESSION = requests.Session()
_HTTP_SESSION.trust_env = False


def _parse_float_env(name: str, default: float, *, minimum: float = 0.0) -> float:
    raw = os.getenv(name)
    if raw is None:
        return default
    try:
        value = float(raw)
    except ValueError:
        return default
    return max(value, minimum)


@lru_cache(maxsize=1)
def _load_signing_key() -> tuple[Ed25519PrivateKey, str]:
    private_key_path, source = resolve_private_key_path(allow_missing=False)
    assert private_key_path is not None

    key_bytes = private_key_path.read_bytes()
    key = serialization.load_pem_private_key(key_bytes, password=None)
    if not isinstance(key, Ed25519PrivateKey):
        raise RuntimeError(
            f"Revolut private key at {private_key_path} is not Ed25519"
        )
    return key, source


def _build_signed_headers(
    *,
    method: str,
    path: str,
    params: dict | None = None,
    payload: dict | None = None,
) -> dict:
    global _MISSING_AUTH_WARNED
    global _MISSING_SIGNING_WARNED

    headers = {
        "Accept": "application/json",
        "User-Agent": USER_AGENT,
    }

    api_key, source = load_api_key(allow_missing=True)
    if not api_key:
        if not _MISSING_AUTH_WARNED:
            logger.warning(
                "Authenticated Revolut request blocked because API key is missing. "
                "Set REVBOT_REVOLUT_API_KEY or revolut-keys/api_key.txt."
            )
            _MISSING_AUTH_WARNED = True
        raise RuntimeError("Revolut API key unavailable for authenticated request")

    timestamp = str(int(time.time() * 1000))
    method_upper = method.upper().strip()

    query = urlencode(params or {}, doseq=True)
    request_path = f"/api/1.0{path}"

    body = ""
    if payload is not None:
        body = json.dumps(payload, separators=(",", ":"), ensure_ascii=False)

    # Revolut X signature contract concatenates query string without '?' separator:
    # timestamp + METHOD + /api/... + query + body
    message = f"{timestamp}{method_upper}{request_path}{query}{body}".encode("utf-8")

    try:
        private_key, key_source = _load_signing_key()
    except Exception as exc:
        if not _MISSING_SIGNING_WARNED:
            logger.warning(
                "Authenticated Revolut request blocked because private signing key is unavailable/invalid. "
                "Set REVBOT_REVOLUT_PRIVATE_KEY_PATH or revolut-keys/private.pem."
            )
            _MISSING_SIGNING_WARNED = True
        raise RuntimeError("Revolut private signing key unavailable") from exc

    signature = private_key.sign(message)
    signature_b64 = base64.b64encode(signature).decode("ascii")

    logger.debug(
        "Using Revolut auth credentials from "
        f"{source} and {key_source} for {method_upper} {path}"
    )
    headers["X-Revx-API-Key"] = api_key
    headers["X-Revx-Timestamp"] = timestamp
    headers["X-Revx-Signature"] = signature_b64
    return headers


def _headers(auth_required: bool = False) -> dict:
    if auth_required:
        return _build_signed_headers(method="GET", path="/balances")
    return {
        "Accept": "application/json",
        "User-Agent": USER_AGENT,
    }


def _throttle_public_request():
    now = time.time()

    while _PUBLIC_REQUEST_TIMES and (now - _PUBLIC_REQUEST_TIMES[0]) >= PUBLIC_WINDOW_SECONDS:
        _PUBLIC_REQUEST_TIMES.popleft()

    if len(_PUBLIC_REQUEST_TIMES) >= PUBLIC_MAX_REQUESTS:
        sleep_for = PUBLIC_WINDOW_SECONDS - (now - _PUBLIC_REQUEST_TIMES[0]) + PUBLIC_THROTTLE_PADDING
        sleep_for = max(sleep_for, PUBLIC_THROTTLE_PADDING)
        _PUBLIC_THROTTLE_EVENTS.append((time.time(), float(sleep_for)))
        logger.info(f"Public API throttle active, sleeping {sleep_for:.2f}s")
        time.sleep(sleep_for)
        now = time.time()

        while _PUBLIC_REQUEST_TIMES and (now - _PUBLIC_REQUEST_TIMES[0]) >= PUBLIC_WINDOW_SECONDS:
            _PUBLIC_REQUEST_TIMES.popleft()

    _PUBLIC_REQUEST_TIMES.append(time.time())


def _get(path: str, params: dict | None = None, auth: bool = False) -> dict:
    url = f"{BASE_URL}{path}"
    logger.debug(f"GET {url} params={params}")
    is_public = not auth and path.startswith("/public/")

    last_response = None
    for attempt in range(MAX_RETRIES + 1):
        if is_public:
            _throttle_public_request()

        response = _HTTP_SESSION.get(
            url,
            headers=(
                _build_signed_headers(method="GET", path=path, params=params)
                if auth
                else {
                    "Accept": "application/json",
                    "User-Agent": USER_AGENT,
                }
            ),
            params=params,
            timeout=REQUEST_TIMEOUT_SECONDS,
            allow_redirects=False,
            proxies={},
        )
        last_response = response

        if response.status_code not in RETRYABLE_STATUS_CODES:
            response.raise_for_status()
            return response.json()

        if attempt >= MAX_RETRIES:
            break
        _PUBLIC_RATE_LIMIT_TIMES.append(time.time())

        retry_after = response.headers.get("Retry-After")
        try:
            wait_seconds = float(retry_after)
        except (TypeError, ValueError):
            wait_seconds = PUBLIC_WINDOW_SECONDS / 2

        if path.startswith("/public/order-book/"):
            max_wait = _parse_float_env(
                "REVBOT_PUBLIC_ORDERBOOK_RETRY_MAX_WAIT_SECONDS",
                1.0,
                minimum=0.5,
            )
        else:
            max_wait = _parse_float_env(
                "REVBOT_PUBLIC_RETRY_MAX_WAIT_SECONDS",
                2.0,
                minimum=0.5,
            )
        wait_seconds = max(wait_seconds, 1.0)
        wait_seconds = min(wait_seconds, max_wait)
        logger.warning(
            f"Public API rate limited on {path}, retrying in {wait_seconds:.2f}s"
        )
        time.sleep(wait_seconds)

    assert last_response is not None
    last_response.raise_for_status()
    return last_response.json()


def _post(path: str, payload: dict, auth: bool = True) -> dict:
    url = f"{BASE_URL}{path}"
    logger.debug(f"POST {url}")

    response = _HTTP_SESSION.post(
        url,
        headers=(
            _build_signed_headers(method="POST", path=path, payload=payload)
            if auth
            else {
                "Accept": "application/json",
                "User-Agent": USER_AGENT,
            }
        ),
        json=payload,
        timeout=REQUEST_TIMEOUT_SECONDS,
        allow_redirects=False,
        proxies={},
    )

    response.raise_for_status()
    return response.json()


def get_public_api_health(*, window_seconds: float = 60.0) -> dict:
    now = time.time()
    window = max(float(window_seconds), 1.0)
    cutoff = now - window

    while _PUBLIC_RATE_LIMIT_TIMES and _PUBLIC_RATE_LIMIT_TIMES[0] < cutoff:
        _PUBLIC_RATE_LIMIT_TIMES.popleft()
    while _PUBLIC_THROTTLE_EVENTS and _PUBLIC_THROTTLE_EVENTS[0][0] < cutoff:
        _PUBLIC_THROTTLE_EVENTS.popleft()

    throttle_sleep_sum = float(sum(wait for _, wait in _PUBLIC_THROTTLE_EVENTS))
    return {
        "window_seconds": window,
        "rate_limited_count": len(_PUBLIC_RATE_LIMIT_TIMES),
        "throttle_event_count": len(_PUBLIC_THROTTLE_EVENTS),
        "throttle_sleep_seconds_sum": throttle_sleep_sum,
        "public_window_seconds": float(PUBLIC_WINDOW_SECONDS),
        "public_max_requests": int(PUBLIC_MAX_REQUESTS),
    }
