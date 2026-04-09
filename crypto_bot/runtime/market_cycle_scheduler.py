from __future__ import annotations

import time
from pathlib import Path
from typing import Callable


def normalize_symbols(raw_symbols: list[str]) -> list[str]:
    seen: set[str] = set()
    normalized: list[str] = []
    for symbol in raw_symbols:
        if not isinstance(symbol, str):
            continue
        cleaned = symbol.strip().upper()
        if not cleaned or cleaned in seen:
            continue
        seen.add(cleaned)
        normalized.append(cleaned)
    return normalized


def as_positive_float(value, default: float) -> float:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return default
    if parsed <= 0:
        return default
    return parsed


def as_positive_int(value, default: int) -> int:
    try:
        parsed = int(float(value))
    except (TypeError, ValueError):
        return default
    if parsed <= 0:
        return default
    return parsed


def as_bool(value, default: bool) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value)
    if isinstance(value, str):
        normalized = value.strip().lower()
        if normalized in {"1", "true", "yes", "on"}:
            return True
        if normalized in {"0", "false", "no", "off"}:
            return False
    return default


def strategy_priority_rank(
    *,
    cfg: dict,
    symbols: list[str],
    state_dir: Path,
    read_json: Callable[[Path, dict], dict],
) -> list[str]:
    if not symbols:
        return []
    state = read_json(state_dir / "strategy_state.json", default={})
    if not isinstance(state, dict):
        return symbols

    raw_scores = state.get("last_score", {})
    raw_volatility = state.get("last_volatility", {})
    score_map = raw_scores if isinstance(raw_scores, dict) else {}
    volatility_map = raw_volatility if isinstance(raw_volatility, dict) else {}

    def _score(symbol: str) -> float:
        score_raw = score_map.get(symbol, 0)
        volatility_raw = volatility_map.get(symbol, 0)
        try:
            score = float(score_raw)
        except (TypeError, ValueError):
            score = 0.0
        try:
            volatility = float(volatility_raw)
        except (TypeError, ValueError):
            volatility = 0.0
        return score + (volatility * 10_000.0)

    return sorted(symbols, key=lambda symbol: (_score(symbol), symbol), reverse=True)


def symbols_for_scan(
    *,
    cfg: dict,
    executor,
    state_dir: Path,
    read_json: Callable[[Path, dict], dict],
) -> list[str]:
    market_data_cfg = cfg.get("market_data", {})
    if not isinstance(market_data_cfg, dict):
        market_data_cfg = {}

    configured_symbols = normalize_symbols(cfg.get("symbols", []))
    tiered_symbols: list[str] = []
    inactive_tier_symbols: list[str] = []
    tiers_raw = market_data_cfg.get("symbol_tiers")
    if isinstance(tiers_raw, dict):
        active_tiers_raw = market_data_cfg.get("active_tiers", ["tier1", "tier2"])
        active_tiers: list[str] = []
        if isinstance(active_tiers_raw, list):
            for item in active_tiers_raw:
                key = str(item or "").strip().lower()
                if key in {"tier1", "tier2", "tier3"} and key not in active_tiers:
                    active_tiers.append(key)
        if not active_tiers:
            active_tiers = ["tier1", "tier2"]

        for tier in active_tiers:
            values = tiers_raw.get(tier)
            if not isinstance(values, list):
                continue
            tiered_symbols.extend(normalize_symbols(values))
        for tier_name, values in tiers_raw.items():
            tier_key = str(tier_name or "").strip().lower()
            if tier_key in active_tiers:
                continue
            if not isinstance(values, list):
                continue
            inactive_tier_symbols.extend(normalize_symbols(values))

    base_symbols = tiered_symbols or configured_symbols
    open_symbols = executor.open_symbols() if executor else []
    dynamic_tiering_enabled = bool(market_data_cfg.get("dynamic_tiering_enabled", False))
    promoted_symbols: list[str] = []
    if dynamic_tiering_enabled and inactive_tier_symbols:
        promotion_count = as_positive_int(
            market_data_cfg.get("dynamic_tier_promotion_count"),
            4,
        )
        ranked_inactive = strategy_priority_rank(
            cfg=cfg,
            symbols=normalize_symbols(inactive_tier_symbols),
            state_dir=state_dir,
            read_json=read_json,
        )
        promoted_symbols = ranked_inactive[:promotion_count]
    return normalize_symbols(base_symbols + promoted_symbols + open_symbols)


def resolve_sync_symbol_scope(cfg: dict) -> str:
    market_data_cfg = cfg.get("market_data", {})
    if not isinstance(market_data_cfg, dict):
        return "scan"
    raw = str(market_data_cfg.get("sync_symbol_scope", "scan") or "").strip().lower()
    if raw in {"cycle", "scan", "scan_plus_open"}:
        return raw
    return "scan"


def sync_symbols_for_tick(
    *,
    cfg: dict,
    scan_symbols: list[str],
    cycle_symbols: list[str],
    open_symbols: list[str],
    stale_symbols: list[str] | None = None,
) -> list[str]:
    scope = resolve_sync_symbol_scope(cfg)
    market_data_cfg = cfg.get("market_data", {})
    if not isinstance(market_data_cfg, dict):
        market_data_cfg = {}
    if scope == "cycle":
        selected = normalize_symbols(cycle_symbols)
    elif scope == "scan_plus_open":
        selected = normalize_symbols(scan_symbols + open_symbols)
    else:
        selected = normalize_symbols(scan_symbols)

    stale_catchup_enabled = as_bool(market_data_cfg.get("sync_stale_catchup_enabled"), True)
    stale_catchup_max_symbols = as_positive_int(
        market_data_cfg.get("sync_stale_catchup_max_symbols"),
        8,
    )
    if not stale_catchup_enabled or stale_catchup_max_symbols <= 0:
        return selected

    stale = normalize_symbols(stale_symbols or [])
    if not stale:
        return selected
    stale = stale[:stale_catchup_max_symbols]
    return normalize_symbols(selected + stale)


def polling_settings(
    *,
    cfg: dict,
    default_fast_poll_seconds: float,
    default_mid_poll_seconds: float,
    default_slow_poll_seconds: float,
    default_top_opportunity_count: int,
    default_mid_tier_count: int,
    default_max_symbols_per_cycle: int,
    default_watchlist_poll_seconds: float,
) -> dict:
    market_data_cfg = cfg.get("market_data", {})
    if not isinstance(market_data_cfg, dict):
        market_data_cfg = {}

    fast = as_positive_float(
        market_data_cfg.get("fast_poll_seconds"),
        default_fast_poll_seconds,
    )
    mid = as_positive_float(
        market_data_cfg.get("mid_poll_seconds"),
        default_mid_poll_seconds,
    )
    slow = as_positive_float(
        market_data_cfg.get("slow_poll_seconds"),
        default_slow_poll_seconds,
    )
    if mid < fast:
        mid = fast
    if slow < mid:
        slow = mid

    return {
        "fast_poll_seconds": fast,
        "mid_poll_seconds": mid,
        "slow_poll_seconds": slow,
        "top_opportunity_count": as_positive_int(
            market_data_cfg.get("top_opportunity_count"),
            default_top_opportunity_count,
        ),
        "mid_tier_count": as_positive_int(
            market_data_cfg.get("mid_tier_count"),
            default_mid_tier_count,
        ),
        "max_symbols_per_cycle": as_positive_int(
            market_data_cfg.get("max_symbols_per_cycle"),
            default_max_symbols_per_cycle,
        ),
        "watchlist_poll_seconds": as_positive_float(
            market_data_cfg.get("watchlist_poll_seconds"),
            default_watchlist_poll_seconds,
        ),
    }


def build_symbol_poll_intervals(
    *,
    cfg: dict,
    scan_symbols: list[str],
    open_symbols: list[str],
    state_dir: Path,
    read_json: Callable[[Path, dict], dict],
    symbol_watchlist_until: dict[str, float],
    default_fast_poll_seconds: float,
    default_mid_poll_seconds: float,
    default_slow_poll_seconds: float,
    default_top_opportunity_count: int,
    default_mid_tier_count: int,
    default_max_symbols_per_cycle: int,
    default_watchlist_poll_seconds: float,
) -> dict[str, float]:
    settings = polling_settings(
        cfg=cfg,
        default_fast_poll_seconds=default_fast_poll_seconds,
        default_mid_poll_seconds=default_mid_poll_seconds,
        default_slow_poll_seconds=default_slow_poll_seconds,
        default_top_opportunity_count=default_top_opportunity_count,
        default_mid_tier_count=default_mid_tier_count,
        default_max_symbols_per_cycle=default_max_symbols_per_cycle,
        default_watchlist_poll_seconds=default_watchlist_poll_seconds,
    )
    configured_symbols = normalize_symbols(cfg.get("symbols", []))
    priority_rank = strategy_priority_rank(
        cfg=cfg,
        symbols=configured_symbols,
        state_dir=state_dir,
        read_json=read_json,
    )
    open_set = set(normalize_symbols(open_symbols))

    top_symbols = [symbol for symbol in priority_rank if symbol not in open_set][
        : settings["top_opportunity_count"]
    ]
    top_set = set(top_symbols)

    mid_candidates = [
        symbol for symbol in priority_rank if symbol not in open_set and symbol not in top_set
    ][: settings["mid_tier_count"]]
    mid_set = set(mid_candidates)

    intervals: dict[str, float] = {}
    now_epoch = time.time()
    for symbol in scan_symbols:
        if symbol in open_set or symbol in top_set:
            intervals[symbol] = settings["fast_poll_seconds"]
        elif symbol in mid_set:
            intervals[symbol] = settings["mid_poll_seconds"]
        else:
            intervals[symbol] = settings["slow_poll_seconds"]
        watch_until = float(symbol_watchlist_until.get(symbol, 0.0))
        if symbol not in open_set and watch_until > now_epoch:
            intervals[symbol] = max(intervals[symbol], settings["watchlist_poll_seconds"])
    return intervals


def select_symbols_for_cycle(
    *,
    symbols: list[str],
    now_epoch: float,
    last_polled_at: dict[str, float],
    interval_by_symbol: dict[str, float],
    max_symbols_per_cycle: int,
    default_slow_poll_seconds: float,
) -> list[str]:
    due: list[tuple[str, float, float]] = []
    for symbol in symbols:
        interval = float(interval_by_symbol.get(symbol, default_slow_poll_seconds))
        last_ts = float(last_polled_at.get(symbol, 0.0))
        elapsed = now_epoch - last_ts
        if elapsed >= interval:
            due.append((symbol, interval, elapsed))

    if not due:
        return []

    due.sort(key=lambda row: (row[1], -row[2], row[0]))
    selected = [row[0] for row in due[: max(1, max_symbols_per_cycle)]]
    for symbol in selected:
        last_polled_at[symbol] = now_epoch
    return selected
