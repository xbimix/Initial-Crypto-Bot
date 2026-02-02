import requests
from pathlib import Path

from utils.logger import setup_logger

logger = setup_logger("revolut_api")

BASE_URL = "https://revx.revolut.com/api/1.0"

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


def _get(path: str, params: dict | None = None, auth: bool = False) -> dict:
    url = f"{BASE_URL}{path}"
    logger.debug(f"GET {url} params={params}")

    response = requests.get(
        url,
        headers=_headers(auth),
        params=params,
        timeout=10,
    )

    response.raise_for_status()
    return response.json()


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
