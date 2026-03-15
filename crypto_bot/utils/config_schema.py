from __future__ import annotations

import copy
from typing import Any

CONFIG_SCHEMA_VERSION = 1


def _to_float(value: Any):
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _to_int(value: Any):
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return None


def _to_bool(value: Any, default: bool) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value)
    if isinstance(value, str):
        raw = value.strip().lower()
        if raw in {"1", "true", "yes", "on"}:
            return True
        if raw in {"0", "false", "no", "off"}:
            return False
    return default


def normalize_config(
    raw_cfg: dict[str, Any],
    *,
    strict: bool = False,
) -> tuple[dict[str, Any], list[str], bool]:
    if not isinstance(raw_cfg, dict):
        raise ValueError("config.json must contain an object")

    cfg = copy.deepcopy(raw_cfg)
    warnings: list[str] = []
    changed = False

    def warn(message: str):
        warnings.append(message)

    def ensure_dict(container: dict[str, Any], key: str, path: str) -> dict[str, Any]:
        nonlocal changed
        value = container.get(key)
        if isinstance(value, dict):
            return value
        container[key] = {}
        changed = True
        warn(f"{path} was missing/invalid; replaced with object")
        return container[key]

    def set_default(container: dict[str, Any], key: str, value: Any, path: str):
        nonlocal changed
        if key not in container:
            container[key] = value
            changed = True
            warn(f"{path} missing; defaulted to {value!r}")

    def normalize_float(
        container: dict[str, Any],
        key: str,
        default: float | None,
        path: str,
        *,
        min_value: float | None = None,
        max_value: float | None = None,
        allow_missing: bool = False,
    ):
        nonlocal changed
        if key not in container:
            if allow_missing:
                return
            container[key] = default
            changed = True
            warn(f"{path} missing; defaulted to {default!r}")
            return

        raw = container.get(key)
        if raw is None and allow_missing:
            return

        numeric = _to_float(raw)
        if numeric is None:
            container[key] = default
            changed = True
            warn(f"{path} invalid; defaulted to {default!r}")
            return

        if min_value is not None and numeric < min_value:
            numeric = min_value
            changed = True
            warn(f"{path} below minimum; clamped to {min_value}")
        if max_value is not None and numeric > max_value:
            numeric = max_value
            changed = True
            warn(f"{path} above maximum; clamped to {max_value}")

        if container.get(key) != numeric:
            container[key] = numeric
            changed = True

    def normalize_int(
        container: dict[str, Any],
        key: str,
        default: int,
        path: str,
        *,
        min_value: int | None = None,
        max_value: int | None = None,
    ):
        nonlocal changed
        raw = container.get(key)
        if raw is None:
            container[key] = default
            changed = True
            warn(f"{path} missing; defaulted to {default}")
            return

        numeric = _to_int(raw)
        if numeric is None:
            container[key] = default
            changed = True
            warn(f"{path} invalid; defaulted to {default}")
            return

        if min_value is not None and numeric < min_value:
            numeric = min_value
            changed = True
            warn(f"{path} below minimum; clamped to {min_value}")
        if max_value is not None and numeric > max_value:
            numeric = max_value
            changed = True
            warn(f"{path} above maximum; clamped to {max_value}")

        if container.get(key) != numeric:
            container[key] = numeric
            changed = True

    def normalize_bool(container: dict[str, Any], key: str, default: bool, path: str):
        nonlocal changed
        if key not in container:
            container[key] = default
            changed = True
            warn(f"{path} missing; defaulted to {default}")
            return
        value = _to_bool(container.get(key), default)
        if container.get(key) != value:
            container[key] = value
            changed = True
            warn(f"{path} invalid; coerced to {value}")

    def normalize_symbol_list():
        nonlocal changed
        raw_symbols = cfg.get("symbols", [])
        cleaned: list[str] = []
        seen: set[str] = set()

        if isinstance(raw_symbols, list):
            for item in raw_symbols:
                if not isinstance(item, str):
                    warn("symbols contains non-string value; item removed")
                    changed = True
                    continue
                symbol = item.strip().upper()
                if not symbol:
                    warn("symbols contains empty string; item removed")
                    changed = True
                    continue
                if symbol in seen:
                    changed = True
                    continue
                seen.add(symbol)
                cleaned.append(symbol)
        else:
            warn("symbols invalid; reset to []")
            changed = True

        if cfg.get("symbols") != cleaned:
            cfg["symbols"] = cleaned
            changed = True

    def normalize_bool_map(key: str):
        nonlocal changed
        raw_map = cfg.get(key, {})
        if not isinstance(raw_map, dict):
            cfg[key] = {}
            changed = True
            warn(f"{key} invalid; reset to empty object")
            return

        cleaned: dict[str, bool] = {}
        for raw_symbol, raw_enabled in raw_map.items():
            if not isinstance(raw_symbol, str):
                changed = True
                warn(f"{key} contains non-string symbol; entry removed")
                continue
            symbol = raw_symbol.strip().upper()
            if not symbol:
                changed = True
                continue
            cleaned[symbol] = _to_bool(raw_enabled, True)

        if raw_map != cleaned:
            cfg[key] = cleaned
            changed = True

    def normalize_symbol_number_map(container: dict[str, Any], key: str, path: str):
        nonlocal changed
        raw_map = container.get(key, {})
        if not isinstance(raw_map, dict):
            container[key] = {}
            changed = True
            warn(f"{path} invalid; reset to empty object")
            return

        cleaned: dict[str, float] = {}
        for raw_symbol, raw_value in raw_map.items():
            if not isinstance(raw_symbol, str):
                changed = True
                warn(f"{path} contains non-string symbol; entry removed")
                continue
            symbol = raw_symbol.strip().upper()
            if not symbol:
                changed = True
                continue
            numeric = _to_float(raw_value)
            if numeric is None or numeric < 0:
                changed = True
                warn(f"{path}.{symbol} invalid; entry removed")
                continue
            cleaned[symbol] = numeric

        if raw_map != cleaned:
            container[key] = cleaned
            changed = True

    # Schema version marker.
    current_version = _to_int(cfg.get("config_version"))
    if current_version is None or current_version < CONFIG_SCHEMA_VERSION:
        cfg["config_version"] = CONFIG_SCHEMA_VERSION
        changed = True
        warn(f"config_version upgraded to {CONFIG_SCHEMA_VERSION}")

    # Top-level defaults and normalization.
    normalize_bool(cfg, "enabled", False, "enabled")
    normalize_bool(cfg, "emergency_stop", False, "emergency_stop")
    normalize_float(cfg, "starting_balance", 10000.0, "starting_balance", min_value=0.0)
    normalize_int(cfg, "lookback", 200, "lookback", min_value=20)
    normalize_int(cfg, "min_trades", 3, "min_trades", min_value=1)
    normalize_int(cfg, "loop_sleep", 10, "loop_sleep", min_value=1)
    set_default(cfg, "execution_mode", "paper", "execution_mode")
    set_default(cfg, "log_level", "INFO", "log_level")

    normalize_symbol_list()
    normalize_bool_map("symbol_enabled")
    normalize_bool_map("symbol_buy_enabled")
    normalize_bool_map("symbol_sell_enabled")

    # Risk section.
    risk = ensure_dict(cfg, "risk", "risk")
    normalize_float(risk, "risk_percent", 0.02, "risk.risk_percent", min_value=0.0, max_value=1.0)
    normalize_float(
        risk,
        "trade_amount_usd",
        None,
        "risk.trade_amount_usd",
        min_value=0.0,
        allow_missing=True,
    )
    normalize_int(risk, "max_concurrent_trades", 1, "risk.max_concurrent_trades", min_value=1)
    normalize_int(
        risk,
        "max_concurrent_trades_per_token",
        1,
        "risk.max_concurrent_trades_per_token",
        min_value=1,
    )
    normalize_float(
        risk,
        "max_trade_amount_usd",
        float(cfg.get("starting_balance", 10000.0)),
        "risk.max_trade_amount_usd",
        min_value=0.0,
    )
    normalize_float(
        risk,
        "max_portfolio_exposure_pct",
        100.0,
        "risk.max_portfolio_exposure_pct",
        min_value=1.0,
    )
    normalize_float(
        risk,
        "max_exposure_per_token_pct",
        100.0,
        "risk.max_exposure_per_token_pct",
        min_value=1.0,
    )
    normalize_float(risk, "cooldown_seconds", 90.0, "risk.cooldown_seconds", min_value=0.0)
    normalize_float(risk, "daily_loss_limit_usd", 0.0, "risk.daily_loss_limit_usd", min_value=0.0)
    normalize_bool(risk, "daily_loss_auto_pause", True, "risk.daily_loss_auto_pause")
    normalize_bool(risk, "daily_loss_close_all", False, "risk.daily_loss_close_all")
    normalize_float(
        risk,
        "stale_losing_review_age_hours",
        36.0,
        "risk.stale_losing_review_age_hours",
        min_value=0.0,
    )
    normalize_float(
        risk,
        "stale_losing_review_unrealized_pnl_pct",
        -10.0,
        "risk.stale_losing_review_unrealized_pnl_pct",
        max_value=0.0,
    )
    normalize_int(
        risk,
        "signal_confirmation_cycles",
        1,
        "risk.signal_confirmation_cycles",
        min_value=1,
    )

    trade_window = ensure_dict(risk, "trade_window_utc", "risk.trade_window_utc")
    normalize_bool(trade_window, "enabled", False, "risk.trade_window_utc.enabled")
    normalize_int(
        trade_window,
        "start_hour_utc",
        0,
        "risk.trade_window_utc.start_hour_utc",
        min_value=0,
        max_value=23,
    )
    normalize_int(
        trade_window,
        "end_hour_utc",
        23,
        "risk.trade_window_utc.end_hour_utc",
        min_value=0,
        max_value=23,
    )
    normalize_symbol_number_map(risk, "symbol_cooldown_seconds", "risk.symbol_cooldown_seconds")

    # Profit lock section.
    profit = ensure_dict(cfg, "profit_locks", "profit_locks")
    normalize_float(profit, "first_activation", 0.02, "profit_locks.first_activation", min_value=0.0)
    normalize_float(profit, "initial_lock", 0.01, "profit_locks.initial_lock", min_value=0.0)
    normalize_float(
        profit,
        "trailing_activation",
        0.10,
        "profit_locks.trailing_activation",
        min_value=0.0,
    )
    normalize_float(profit, "trailing_gap", 0.02, "profit_locks.trailing_gap", min_value=0.0)
    normalize_bool(profit, "reset_below_activation", True, "profit_locks.reset_below_activation")
    normalize_float(
        profit,
        "max_negative_z_score",
        -3.0,
        "profit_locks.max_negative_z_score",
    )

    levels_raw = profit.get("levels")
    default_levels = [[0.04, 0.03], [0.05, 0.04], [0.06, 0.05], [0.08, 0.06]]
    cleaned_levels: list[list[float]] = []
    if isinstance(levels_raw, list):
        for pair in levels_raw:
            if not isinstance(pair, (list, tuple)) or len(pair) != 2:
                changed = True
                warn("profit_locks.levels contains invalid entry; entry removed")
                continue
            trigger = _to_float(pair[0])
            lock = _to_float(pair[1])
            if trigger is None or lock is None or trigger < 0 or lock < 0:
                changed = True
                warn("profit_locks.levels contains non-numeric/negative entry; entry removed")
                continue
            cleaned_levels.append([trigger, lock])
    if not cleaned_levels:
        cleaned_levels = default_levels
        if levels_raw != cleaned_levels:
            changed = True
            warn("profit_locks.levels missing/invalid; default sequence applied")
    if profit.get("levels") != cleaned_levels:
        profit["levels"] = cleaned_levels
        changed = True

    # Market-data section.
    market_data = ensure_dict(cfg, "market_data", "market_data")
    normalize_int(market_data, "history_seconds", 86400, "market_data.history_seconds", min_value=60)
    normalize_int(market_data, "min_history_points", 8, "market_data.min_history_points", min_value=2)
    normalize_float(market_data, "max_spread_bps", 150.0, "market_data.max_spread_bps", min_value=0.0)
    normalize_float(
        market_data,
        "max_book_trade_gap_pct",
        0.02,
        "market_data.max_book_trade_gap_pct",
        min_value=0.0,
    )
    normalize_int(
        market_data,
        "trade_confirmation_limit",
        100,
        "market_data.trade_confirmation_limit",
        min_value=0,
    )

    # Volatility filters.
    volatility = ensure_dict(cfg, "volatility_filters", "volatility_filters")
    normalize_float(volatility, "min_atr", 0.0, "volatility_filters.min_atr", min_value=0.0)
    normalize_float(volatility, "min_atr_pct", 0.0, "volatility_filters.min_atr_pct", min_value=0.0)
    normalize_float(
        volatility,
        "max_trade_jump_pct",
        0.12,
        "volatility_filters.max_trade_jump_pct",
        min_value=0.0,
    )

    # Market regime defaults required by strategy loader.
    regime = ensure_dict(cfg, "market_regime", "market_regime")
    raw_zone = regime.get("preferred_buy_zone")
    default_zone = [0.05, 0.30]
    zone = default_zone
    if isinstance(raw_zone, (list, tuple)) and len(raw_zone) == 2:
        lo = _to_float(raw_zone[0])
        hi = _to_float(raw_zone[1])
        if lo is not None and hi is not None and lo >= 0 and hi >= lo:
            zone = [lo, hi]
    if regime.get("preferred_buy_zone") != zone:
        regime["preferred_buy_zone"] = zone
        changed = True
    normalize_float(regime, "min_z_score", -1.5, "market_regime.min_z_score")

    if strict and warnings:
        raise ValueError("Config validation failed: " + "; ".join(warnings))

    return cfg, warnings, changed
