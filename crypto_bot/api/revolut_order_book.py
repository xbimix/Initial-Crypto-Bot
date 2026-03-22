import os
import time

from api.revolut_api import _get
from utils.logger import setup_logger

logger = setup_logger("revolut_order_book")
_AUTH_ORDERBOOK_UNAVAILABLE_UNTIL_EPOCH = 0.0


def _auth_cooldown_seconds() -> float:
    raw = os.getenv("REVBOT_ORDERBOOK_AUTH_COOLDOWN_SECONDS", "600")
    try:
        value = float(raw)
    except (TypeError, ValueError):
        value = 600.0
    return max(30.0, value)


def _normalize_limit(limit: int | None) -> int:
    try:
        parsed = int(limit if limit is not None else 20)
    except (TypeError, ValueError):
        parsed = 20
    return max(1, min(parsed, 20))


def get_order_book(symbol: str, *, limit: int = 20) -> dict:
    """
    Fetch order book for one trading pair.
    Prefer authenticated endpoint (/order-book/{symbol}) and fall back to
    public endpoint (/public/order-book/{symbol}) if auth scope is unavailable.
    """
    global _AUTH_ORDERBOOK_UNAVAILABLE_UNTIL_EPOCH
    normalized_limit = _normalize_limit(limit)
    params = {"limit": normalized_limit}
    now = time.time()

    # High-frequency healthy event; keep available at DEBUG to reduce log churn.
    logger.debug(f"Fetching order book {symbol}")

    if now >= _AUTH_ORDERBOOK_UNAVAILABLE_UNTIL_EPOCH:
        try:
            return _get(f"/order-book/{symbol}", params=params, auth=True)
        except Exception as exc:
            response = getattr(exc, "response", None)
            status_code = getattr(response, "status_code", None)
            msg = str(exc).lower()
            if status_code in {401, 403} or "api key unavailable" in msg or "private signing key unavailable" in msg:
                _AUTH_ORDERBOOK_UNAVAILABLE_UNTIL_EPOCH = now + _auth_cooldown_seconds()
                logger.warning(
                    "Authenticated order-book unavailable for %s (status=%s); "
                    "falling back to public endpoint for %.0fs",
                    symbol,
                    status_code,
                    _AUTH_ORDERBOOK_UNAVAILABLE_UNTIL_EPOCH - now,
                )
            else:
                logger.debug("Authenticated order-book call failed for %s: %s", symbol, exc)

    return _get(f"/public/order-book/{symbol}", params=params, auth=False)
