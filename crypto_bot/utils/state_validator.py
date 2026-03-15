from __future__ import annotations

import math
import time
from pathlib import Path
from typing import Any

from utils.state_io import read_json_file

STATE_FILES = {
    "paper_state": "paper_state.json",
    "strategy_state": "strategy_state.json",
    "trades": "trades.json",
}


def _is_number(value: Any) -> bool:
    if isinstance(value, bool):
        return False
    if not isinstance(value, (int, float)):
        return False
    return math.isfinite(float(value))


def _validate_timestamp(
    value: Any,
    *,
    label: str,
    errors: list[str],
    now: float,
    future_tolerance_seconds: float,
):
    if value is None:
        return
    if not _is_number(value):
        errors.append(f"{label}: timestamp must be numeric")
        return
    ts = float(value)
    if ts <= 946684800:  # 2000-01-01
        errors.append(f"{label}: timestamp is implausibly old ({ts})")
    if ts > (now + future_tolerance_seconds):
        errors.append(f"{label}: timestamp is in the future ({ts})")


def validate_paper_state(
    paper_state: Any,
    *,
    now: float | None = None,
    future_tolerance_seconds: float = 300.0,
) -> dict[str, Any]:
    errors: list[str] = []
    warnings: list[str] = []
    now_ts = now if _is_number(now) else time.time()

    if not isinstance(paper_state, dict):
        return {
            "ok": False,
            "errors": ["paper_state must be a JSON object"],
            "warnings": [],
        }

    balance = paper_state.get("balance")
    if not _is_number(balance):
        errors.append("paper_state.balance must be numeric")
    elif float(balance) < 0:
        errors.append("paper_state.balance cannot be negative")

    positions = paper_state.get("positions")
    if positions is None:
        errors.append("paper_state.positions is required")
        positions = {}
    if not isinstance(positions, dict):
        errors.append("paper_state.positions must be an object")
        positions = {}

    for symbol, raw_pos in positions.items():
        if not isinstance(raw_pos, dict):
            errors.append(f"positions.{symbol} must be an object")
            continue

        price = raw_pos.get("price")
        size = raw_pos.get("size")
        if not _is_number(price) or float(price) <= 0:
            errors.append(f"positions.{symbol}.price must be > 0")
        if not _is_number(size) or float(size) <= 0:
            errors.append(f"positions.{symbol}.size must be > 0")
        _validate_timestamp(
            raw_pos.get("entry_time"),
            label=f"positions.{symbol}.entry_time",
            errors=errors,
            now=now_ts,
            future_tolerance_seconds=future_tolerance_seconds,
        )

    return {
        "ok": not errors,
        "errors": errors,
        "warnings": warnings,
    }


def validate_trades(
    trades: Any,
    *,
    now: float | None = None,
    future_tolerance_seconds: float = 300.0,
) -> dict[str, Any]:
    errors: list[str] = []
    warnings: list[str] = []
    now_ts = now if _is_number(now) else time.time()

    if not isinstance(trades, list):
        return {
            "ok": False,
            "errors": ["trades must be a JSON array"],
            "warnings": [],
        }

    seen_trade_ids: set[str] = set()

    for index, trade in enumerate(trades):
        label = f"trades[{index}]"
        if not isinstance(trade, dict):
            errors.append(f"{label} must be an object")
            continue

        symbol = str(trade.get("symbol") or "").strip().upper()
        side = str(trade.get("side") or "").strip().upper()
        price = trade.get("price")
        size = trade.get("size")

        if not symbol:
            errors.append(f"{label}.symbol is required")
        if side not in {"BUY", "SELL"}:
            errors.append(f"{label}.side must be BUY or SELL")
        if not _is_number(price) or float(price) <= 0:
            errors.append(f"{label}.price must be > 0")
        if not _is_number(size) or float(size) <= 0:
            errors.append(f"{label}.size must be > 0")

        _validate_timestamp(
            trade.get("time"),
            label=f"{label}.time",
            errors=errors,
            now=now_ts,
            future_tolerance_seconds=future_tolerance_seconds,
        )

        trade_id = trade.get("trade_id", trade.get("id"))
        if trade_id is not None:
            trade_id_key = str(trade_id).strip()
            if not trade_id_key:
                errors.append(f"{label}.trade_id is empty")
            elif trade_id_key in seen_trade_ids:
                errors.append(f"duplicate trade_id detected: {trade_id_key}")
            else:
                seen_trade_ids.add(trade_id_key)

    return {
        "ok": not errors,
        "errors": errors,
        "warnings": warnings,
    }


def validate_strategy_state(strategy_state: Any) -> dict[str, Any]:
    errors: list[str] = []
    warnings: list[str] = []

    if not isinstance(strategy_state, dict):
        return {
            "ok": False,
            "errors": ["strategy_state must be a JSON object"],
            "warnings": [],
        }

    expected_maps = (
        "entry_price",
        "entry_time",
        "profit_lock",
        "peak_pnl",
        "last_signal",
        "last_momentum",
        "last_regime",
        "last_score",
        "last_volatility",
    )
    for key in expected_maps:
        value = strategy_state.get(key)
        if value is None:
            continue
        if not isinstance(value, dict):
            errors.append(f"strategy_state.{key} must be an object")

    return {
        "ok": not errors,
        "errors": errors,
        "warnings": warnings,
    }


def validate_state_files(
    state_dir: str | Path,
    *,
    strict_files_exist: bool = True,
    future_tolerance_seconds: float = 300.0,
) -> dict[str, Any]:
    base = Path(state_dir)
    now = time.time()
    checks: dict[str, Any] = {}
    errors: list[str] = []
    warnings: list[str] = []

    for key, file_name in STATE_FILES.items():
        path = base / file_name
        if not path.exists():
            message = f"Missing state file: {file_name}"
            if strict_files_exist:
                errors.append(message)
            else:
                warnings.append(message)
            checks[key] = {
                "ok": False,
                "errors": [message],
                "warnings": [],
            }
            continue

        data = read_json_file(path, default=None, strict=False)
        if key == "paper_state":
            result = validate_paper_state(
                data,
                now=now,
                future_tolerance_seconds=future_tolerance_seconds,
            )
        elif key == "trades":
            result = validate_trades(
                data,
                now=now,
                future_tolerance_seconds=future_tolerance_seconds,
            )
        else:
            result = validate_strategy_state(data)

        checks[key] = result
        errors.extend(result.get("errors", []))
        warnings.extend(result.get("warnings", []))

    return {
        "ok": not errors,
        "errors": errors,
        "warnings": warnings,
        "checks": checks,
    }
