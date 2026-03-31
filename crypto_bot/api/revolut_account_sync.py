from __future__ import annotations

import time
from pathlib import Path

from api.revolut_balances import get_balances
from api.revolut_order_book import get_order_book
from utils.logger import setup_logger
from utils.state_paths import resolve_state_dir
from utils.state_io import read_json_file, write_json_file

logger = setup_logger("revolut_account_sync")

STATE_DIR = resolve_state_dir(Path(__file__).resolve().parent.parent / "state")
ACCOUNT_SNAPSHOT_PATH = STATE_DIR / "revolut_account_snapshot.json"
USD_LIKE_ASSETS = {"USD", "USDT", "USDC", "DAI", "EURC"}


def _to_float(value, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _best_asset_label(raw: dict) -> str:
    for key in ("asset", "currency", "ccy", "symbol", "code", "aid", "id"):
        value = raw.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip().upper()
    return "UNKNOWN"


def _extract_balance_rows(payload: dict) -> list[dict]:
    if not isinstance(payload, dict):
        return []

    data = payload.get("data")
    if isinstance(data, list):
        return [row for row in data if isinstance(row, dict)]
    if isinstance(data, dict):
        nested = data.get("balances")
        if isinstance(nested, list):
            return [row for row in nested if isinstance(row, dict)]
    balances = payload.get("balances")
    if isinstance(balances, list):
        return [row for row in balances if isinstance(row, dict)]
    return []


def _estimate_symbol_mid_price(symbol: str) -> float | None:
    try:
        payload = get_order_book(symbol)
    except Exception:
        return None

    data = payload.get("data", {}) if isinstance(payload, dict) else {}
    asks = data.get("asks")
    bids = data.get("bids")
    if not isinstance(asks, list) or not isinstance(bids, list):
        return None

    best_ask = None
    for row in asks:
        if not isinstance(row, dict):
            continue
        price = _to_float(row.get("p"), default=0.0)
        if price <= 0:
            continue
        best_ask = price if best_ask is None else min(best_ask, price)

    best_bid = None
    for row in bids:
        if not isinstance(row, dict):
            continue
        price = _to_float(row.get("p"), default=0.0)
        if price <= 0:
            continue
        best_bid = price if best_bid is None else max(best_bid, price)

    if best_ask is None or best_bid is None:
        return None
    if best_bid > best_ask:
        return None
    return (best_ask + best_bid) / 2.0


def _estimate_quote_value(asset: str, total: float) -> tuple[float | None, str | None]:
    if total <= 0:
        return 0.0, "zero_balance"
    if asset in USD_LIKE_ASSETS:
        return total, "usd_like"

    symbol = f"{asset}-USD"
    mid = _estimate_symbol_mid_price(symbol)
    if mid is None:
        return None, "price_unavailable"
    return total * mid, "mid_price"


def _build_snapshot_from_payload(payload: dict) -> dict:
    rows = _extract_balance_rows(payload)
    parsed = []
    total_estimated_quote_value = 0.0
    estimated_quote_value_available = True

    for row in rows:
        asset = _best_asset_label(row)
        available = _to_float(
            row.get("available", row.get("free", row.get("balance", row.get("amount", 0.0))))
        )
        locked = _to_float(
            row.get("locked", row.get("hold", row.get("frozen", row.get("in_orders", 0.0))))
        )
        total = max(available, 0.0) + max(locked, 0.0)
        if total <= 0:
            continue

        estimated_quote_value, value_source = _estimate_quote_value(asset, total)
        if estimated_quote_value is None:
            estimated_quote_value_available = False
        else:
            total_estimated_quote_value += estimated_quote_value

        parsed.append(
            {
                "asset": asset,
                "available": round(max(available, 0.0), 12),
                "locked": round(max(locked, 0.0), 12),
                "total": round(total, 12),
                "estimated_quote_value": (
                    None if estimated_quote_value is None else round(float(estimated_quote_value), 6)
                ),
                "estimated_quote_value_source": value_source,
            }
        )

    parsed.sort(key=lambda row: row["asset"])
    return {
        "last_sync_time": time.time(),
        "sync_status": "ok",
        "sync_error": None,
        "assets": parsed,
        "asset_count": len(parsed),
        "estimated_total_quote_value": round(total_estimated_quote_value, 6),
        "estimated_quote_value_complete": bool(estimated_quote_value_available),
        "source": "revolut_x",
    }


def sync_account_snapshot() -> dict:
    try:
        payload = get_balances()
        snapshot = _build_snapshot_from_payload(payload)
    except Exception as exc:
        logger.exception(f"Revolut account sync failed: {exc}")
        previous = read_account_snapshot(default={})
        previous_assets = previous.get("assets") if isinstance(previous, dict) else None
        fallback_assets = previous_assets if isinstance(previous_assets, list) else []
        fallback_total_value = _to_float(
            previous.get("estimated_total_quote_value"),
            default=0.0,
        ) if isinstance(previous, dict) else 0.0
        fallback_complete = bool(previous.get("estimated_quote_value_complete")) if isinstance(previous, dict) else False
        snapshot = {
            "last_sync_time": time.time(),
            "sync_status": "error",
            "sync_error": str(exc),
            "assets": fallback_assets,
            "asset_count": len(fallback_assets),
            "estimated_total_quote_value": round(fallback_total_value, 6),
            "estimated_quote_value_complete": fallback_complete,
            "fallback_from_last_good_snapshot": bool(fallback_assets),
            "last_success_sync_time": (
                previous.get("last_sync_time") if isinstance(previous, dict) else None
            ),
            "source": "revolut_x",
        }

    write_json_file(ACCOUNT_SNAPSHOT_PATH, snapshot, use_lock=True)
    return snapshot


def read_account_snapshot(default: dict | None = None) -> dict:
    fallback = default if isinstance(default, dict) else {}
    snapshot = read_json_file(ACCOUNT_SNAPSHOT_PATH, default=fallback, strict=False)
    if isinstance(snapshot, dict):
        return snapshot
    return fallback
