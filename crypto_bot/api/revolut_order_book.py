import os
import time

from api.revolut_api import _get
from utils.logger import setup_logger

logger = setup_logger("revolut_order_book")
_AUTH_ORDERBOOK_UNAVAILABLE_UNTIL_EPOCH = 0.0


def _env_bool(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    normalized = str(raw).strip().lower()
    if normalized in {"1", "true", "yes", "on"}:
        return True
    if normalized in {"0", "false", "no", "off"}:
        return False
    return default


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


def _resolve_public_fallback(cfg: dict | None, override: bool | None) -> bool:
    if isinstance(override, bool):
        return override
    if isinstance(cfg, dict):
        market_data = cfg.get("market_data", {})
        if isinstance(market_data, dict):
            source_map = market_data.get("source_map", {})
            if isinstance(source_map, dict):
                orderbook = source_map.get("orderbook", {})
                if isinstance(orderbook, dict) and "allow_public_fallback" in orderbook:
                    return bool(orderbook.get("allow_public_fallback"))
    return _env_bool("REVBOT_ORDERBOOK_ALLOW_PUBLIC_FALLBACK", default=True)


def get_order_book(
    symbol: str,
    *,
    limit: int = 20,
    cfg: dict | None = None,
    allow_public_fallback: bool | None = None,
) -> dict:
    """
    Fetch order book for one trading pair.
    Prefer authenticated endpoint (/order-book/{symbol}) and fall back to
    public endpoint (/public/order-book/{symbol}) if auth scope is unavailable.
    """
    global _AUTH_ORDERBOOK_UNAVAILABLE_UNTIL_EPOCH
    normalized_limit = _normalize_limit(limit)
    params = {"limit": normalized_limit}
    now = time.time()
    allow_public = _resolve_public_fallback(cfg, allow_public_fallback)

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
                    "public fallback %s for %.0fs",
                    symbol,
                    status_code,
                    "enabled" if allow_public else "disabled",
                    _AUTH_ORDERBOOK_UNAVAILABLE_UNTIL_EPOCH - now,
                )
            else:
                logger.debug("Authenticated order-book call failed for %s: %s", symbol, exc)
            if not allow_public:
                raise
    if not allow_public:
        raise RuntimeError(
            f"Authenticated order-book unavailable for {symbol}; public fallback disabled"
        )
    return _get(f"/public/order-book/{symbol}", params=params, auth=False)
