import time
from collections import deque
from pathlib import Path

import requests

from utils.logger import setup_logger

logger = setup_logger("revolut_api")

BASE_URL = "https://revx.revolut.com/api/1.0"
PUBLIC_WINDOW_SECONDS = 10.0
PUBLIC_MAX_REQUESTS = 18
PUBLIC_THROTTLE_PADDING = 0.05
RETRYABLE_STATUS_CODES = {429}
MAX_RETRIES = 1
_PUBLIC_REQUEST_TIMES = deque()

API_KEY_PATH = Path("revolut-keys/api_key.txt")

API_KEY = None
if API_KEY_PATH.exists():
    API_KEY = API_KEY_PATH.read_text().strip()
else:
    logger.warning("API key not found — running in public-data-only mode")


def _headers(auth_required: bool = False) -> dict:
    headers = {
        "Accept": "application/json",
    }

    if auth_required and API_KEY:
        headers["X-Revx-API-Key"] = API_KEY

    return headers


def _throttle_public_request():
    now = time.time()

    while _PUBLIC_REQUEST_TIMES and (now - _PUBLIC_REQUEST_TIMES[0]) >= PUBLIC_WINDOW_SECONDS:
        _PUBLIC_REQUEST_TIMES.popleft()

    if len(_PUBLIC_REQUEST_TIMES) >= PUBLIC_MAX_REQUESTS:
        sleep_for = PUBLIC_WINDOW_SECONDS - (now - _PUBLIC_REQUEST_TIMES[0]) + PUBLIC_THROTTLE_PADDING
        sleep_for = max(sleep_for, PUBLIC_THROTTLE_PADDING)
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

        response = requests.get(
            url,
            headers=_headers(auth),
            params=params,
            timeout=10,
        )
        last_response = response

        if response.status_code not in RETRYABLE_STATUS_CODES:
            response.raise_for_status()
            return response.json()

        if attempt >= MAX_RETRIES:
            break

        retry_after = response.headers.get("Retry-After")
        try:
            wait_seconds = float(retry_after)
        except (TypeError, ValueError):
            wait_seconds = PUBLIC_WINDOW_SECONDS / 2

        wait_seconds = max(wait_seconds, 1.0)
        logger.warning(
            f"Public API rate limited on {path}, retrying in {wait_seconds:.2f}s"
        )
        time.sleep(wait_seconds)

    assert last_response is not None
    last_response.raise_for_status()
    return last_response.json()


def _post(path: str, payload: dict, auth: bool = True) -> dict:
    url = f"{BASE_URL}{path}"
    logger.debug(f"POST {url} payload={payload}")

    response = requests.post(
        url,
        headers=_headers(auth),
        json=payload,
        timeout=10,
    )

    response.raise_for_status()
    return response.json()


# import requests
# from utils.logger import logger

# BASE_URL = "https://revx.revolut.com/api/1.0"

# DEFAULT_HEADERS = {
#     "Accept": "application/json",
# }

# def _get(path: str, params: dict | None = None, headers: dict | None = None):
#     url = f"{BASE_URL}{path}"
#     h = DEFAULT_HEADERS.copy()
#     if headers:
#         h.update(headers)

#     logger.debug(f"HTTP GET {url} params={params}")

#     r = requests.get(url, params=params, headers=h, timeout=10)
#     r.raise_for_status()
#     return r.json()
