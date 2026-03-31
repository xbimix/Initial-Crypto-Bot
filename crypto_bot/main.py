import time
import os
import logging
import json
from datetime import datetime, timezone
from pathlib import Path

from api.revolut_api import get_public_api_health
from api.revolut_account_sync import sync_account_snapshot
from api.revolut_universe import build_universe_snapshot
from data.candle_coverage import summarize_core_timeframe_coverage
from data.decision_input_builder import build_decision_context
from data.db_maintenance import run_db_maintenance
from data.live_sync_scheduler import run_incremental_sync_tick
from data.market_data import fetch_market_snapshot
from data.replay_persistence import append_replay_event
from data.revolut_candle_fetcher import get_candle_fetch_telemetry
from strategy.route_quality import load_route_quality_report_cached
from strategy.strategy_engine import evaluate_symbol
from trading.executor import Executor
from runtime.periodic import (
    log_heartbeat_if_due,
    run_account_sync_if_due,
    run_coverage_log_if_due,
    run_db_maintenance_if_due,
    run_housekeeping_if_due,
    run_universe_sync_if_due,
)
from utils.config_loader import load_config
from utils.logger import setup_logger
from utils.runtime_events import append_runtime_event
from utils.runtime_guard import (
    check_disk_space,
    check_timestamp_sanity,
    cleanup_log_rotations,
    cleanup_stale_locks,
    cleanup_temp_files,
)
from utils.state_paths import (
    read_path_with_legacy_fallback,
    resolve_legacy_state_dir,
    resolve_legacy_state_file,
    resolve_state_dir,
    seed_primary_from_legacy,
)
from utils.state_io import read_json_file
from utils.state_snapshot import create_state_snapshot, ensure_daily_snapshot
from utils.state_validator import validate_state_files

logger = setup_logger("main")

HEARTBEAT_INTERVAL = 60
ACCOUNT_SYNC_INTERVAL_SECONDS = 120
UNIVERSE_SYNC_INTERVAL_SECONDS = 300
COVERAGE_LOG_INTERVAL_SECONDS = 300
_buy_signal_streak: dict[str, int] = {}
_symbol_watchlist_until: dict[str, float] = {}
_symbol_health_score: dict[str, float] = {}
DEFAULT_FAST_POLL_SECONDS = 20.0
DEFAULT_MID_POLL_SECONDS = 90.0
DEFAULT_SLOW_POLL_SECONDS = 240.0
DEFAULT_WATCHLIST_POLL_SECONDS = 300.0
DEFAULT_TOP_OPPORTUNITY_COUNT = 12
DEFAULT_MID_TIER_COUNT = 28
DEFAULT_MAX_SYMBOLS_PER_CYCLE = 16
DEFAULT_SYMBOL_HEALTH_MIN_SCORE = 45.0
DEFAULT_SYMBOL_HEALTH_WATCHLIST_SECONDS = 24 * 60 * 60
DEFAULT_ROUTE_QUALITY_MIN_CONFIDENCE = 75.0
DEFAULT_ROUTE_QUALITY_MIN_STABILITY = 60.0
DEFAULT_ROUTE_QUALITY_MIN_PERSISTENCE = 60.0
DEFAULT_ROUTE_QUALITY_MAX_RATE_LIMITED = 2
DEFAULT_STATE_DIR = Path(__file__).resolve().parent / "state"
STATE_DIR = resolve_state_dir(DEFAULT_STATE_DIR)
LEGACY_STATE_DIR = resolve_legacy_state_dir(DEFAULT_STATE_DIR)
MARKET_SYNC_HEALTH_PATH = STATE_DIR / "market_sync_health.json"
MARKET_SYNC_HEALTH_HISTORY_PATH = STATE_DIR / "market_sync_health_history.jsonl"
DECISION_AUDIT_PATH = STATE_DIR / "decision_audit.jsonl"
DECISION_AUDIT_MAX_LINES_DEFAULT = 200000
SYNC_HEALTH_HISTORY_MAX_LINES_DEFAULT = 200000
SYNC_HEALTH_HISTORY_RETENTION_DAYS_DEFAULT = 14.0
SNAPSHOT_RETENTION_DAYS_DEFAULT = 14.0
SNAPSHOT_MAX_DIRS_DEFAULT = 100
REQUIRED_STATE_FILES = (
    "config.json",
    "paper_state.json",
    "strategy_state.json",
    "trades.json",
)


def _seed_required_state_files_from_legacy():
    for filename in REQUIRED_STATE_FILES:
        seed_primary_from_legacy(
            STATE_DIR / filename,
            resolve_legacy_state_file(DEFAULT_STATE_DIR, filename),
        )

ROUTE_GUARD_STREAK_CACHE_TTL_SECONDS = 30.0
_route_guard_cap_hits: dict[str, int] = {}
_route_guard_cooldown_hits: dict[str, int] = {}
_route_guard_confidence_tier_hits: dict[str, int] = {"HIGH": 0, "MEDIUM": 0, "LOW": 0}
_route_guard_loss_streak_cache: dict[str, object] = {
    "mtime": None,
    "computed_at": 0.0,
    "streaks": {},
}
_route_guard_cooldown_until: dict[str, float] = {}


def _bool_env(name: str, default: bool = False) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    normalized = raw.strip().lower()
    if normalized in {"1", "true", "yes", "on"}:
        return True
    if normalized in {"0", "false", "no", "off"}:
        return False
    return default


STRICT_STARTUP_CHECKS = _bool_env("REVBOT_MAIN_STRICT_STARTUP", default=False)


def _now_utc_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _json_dumps_safe(payload: dict) -> str:
    try:
        return json.dumps(payload, ensure_ascii=False)
    except TypeError:
        normalized = {}
        for key, value in payload.items():
            if isinstance(value, (str, int, float, bool)) or value is None:
                normalized[key] = value
            else:
                normalized[key] = str(value)
        return json.dumps(normalized, ensure_ascii=False)


def _parse_positive_int(value, default: int) -> int:
    try:
        parsed = int(float(value))
    except (TypeError, ValueError):
        parsed = default
    return max(1, parsed)


def _parse_positive_float(value, default: float) -> float:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        parsed = default
    return max(0.0, parsed)


def _trim_jsonl_lines(path: Path, *, max_lines: int) -> int:
    if max_lines <= 0 or not path.exists():
        return 0
    try:
        lines = path.read_text(encoding="utf-8", errors="ignore").splitlines()
    except Exception:
        return 0
    if len(lines) <= max_lines:
        return 0
    keep = lines[-max_lines:]
    try:
        path.write_text("\n".join(keep) + "\n", encoding="utf-8")
        return len(lines) - len(keep)
    except Exception:
        return 0


def _prune_market_sync_history(path: Path, *, max_lines: int, retention_days: float) -> int:
    if max_lines <= 0 or not path.exists():
        return 0
    cutoff_epoch = time.time() - max(0.0, retention_days) * 86400.0
    try:
        raw_lines = path.read_text(encoding="utf-8", errors="ignore").splitlines()
    except Exception:
        return 0
    if not raw_lines:
        return 0
    kept: list[str] = []
    for text in raw_lines:
        line = text.strip()
        if not line:
            continue
        try:
            payload = json.loads(line)
        except Exception:
            continue
        if not isinstance(payload, dict):
            continue
        ts = _to_float(payload.get("ts_epoch"), 0.0) or 0.0
        if ts > 0 and ts < cutoff_epoch:
            continue
        kept.append(_json_dumps_safe(payload))
    if len(kept) > max_lines:
        kept = kept[-max_lines:]
    removed_count = len(raw_lines) - len(kept)
    if removed_count <= 0:
        return 0
    try:
        path.write_text("\n".join(kept) + ("\n" if kept else ""), encoding="utf-8")
        return removed_count
    except Exception:
        return 0


def _prune_snapshots(*, snapshots_dir: Path, retention_days: float, max_dirs: int) -> int:
    if not snapshots_dir.exists():
        return 0
    now = time.time()
    cutoff_epoch = now - max(0.0, retention_days) * 86400.0
    dirs: list[Path] = []
    try:
        for row in snapshots_dir.iterdir():
            if row.is_dir():
                dirs.append(row)
    except Exception:
        return 0
    if not dirs:
        return 0
    dirs.sort(key=lambda item: item.stat().st_mtime if item.exists() else 0.0, reverse=True)
    removed = 0
    for idx, directory in enumerate(dirs):
        try:
            mtime = directory.stat().st_mtime
        except Exception:
            continue
        if idx < max_dirs and mtime >= cutoff_epoch:
            continue
        try:
            for child in directory.rglob("*"):
                if child.is_file():
                    child.unlink(missing_ok=True)
            for child in sorted(directory.rglob("*"), reverse=True):
                if child.is_dir():
                    child.rmdir()
            directory.rmdir()
            removed += 1
        except Exception:
            continue
    return removed


def _run_housekeeping(cfg: dict) -> dict:
    market_data_cfg = cfg.get("market_data", {})
    if not isinstance(market_data_cfg, dict):
        market_data_cfg = {}
    sync_history_max_lines = _parse_positive_int(
        market_data_cfg.get("sync_health_history_max_lines"),
        SYNC_HEALTH_HISTORY_MAX_LINES_DEFAULT,
    )
    sync_history_retention_days = _parse_positive_float(
        market_data_cfg.get("sync_health_history_retention_days"),
        SYNC_HEALTH_HISTORY_RETENTION_DAYS_DEFAULT,
    )
    audit_max_lines = _parse_positive_int(
        market_data_cfg.get("decision_audit_max_lines"),
        DECISION_AUDIT_MAX_LINES_DEFAULT,
    )
    snapshot_retention_days = _parse_positive_float(
        market_data_cfg.get("snapshot_retention_days"),
        SNAPSHOT_RETENTION_DAYS_DEFAULT,
    )
    snapshot_max_dirs = _parse_positive_int(
        market_data_cfg.get("snapshot_max_dirs"),
        SNAPSHOT_MAX_DIRS_DEFAULT,
    )
    removed_sync_history = _prune_market_sync_history(
        MARKET_SYNC_HEALTH_HISTORY_PATH,
        max_lines=sync_history_max_lines,
        retention_days=sync_history_retention_days,
    )
    removed_audit = _trim_jsonl_lines(DECISION_AUDIT_PATH, max_lines=audit_max_lines)
    removed_snapshots = _prune_snapshots(
        snapshots_dir=STATE_DIR / "snapshots",
        retention_days=snapshot_retention_days,
        max_dirs=snapshot_max_dirs,
    )
    return {
        "removed_sync_history_lines": int(removed_sync_history),
        "removed_decision_audit_lines": int(removed_audit),
        "removed_snapshots": int(removed_snapshots),
    }


def _normalize_symbols(raw_symbols: list[str]) -> list[str]:
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


def _symbols_for_scan(cfg: dict, executor: Executor | None) -> list[str]:
    market_data_cfg = cfg.get("market_data", {})
    if not isinstance(market_data_cfg, dict):
        market_data_cfg = {}

    configured_symbols = _normalize_symbols(cfg.get("symbols", []))
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
            tiered_symbols.extend(_normalize_symbols(values))
        for tier_name, values in tiers_raw.items():
            tier_key = str(tier_name or "").strip().lower()
            if tier_key in active_tiers:
                continue
            if not isinstance(values, list):
                continue
            inactive_tier_symbols.extend(_normalize_symbols(values))

    base_symbols = tiered_symbols or configured_symbols
    open_symbols = executor.open_symbols() if executor else []
    dynamic_tiering_enabled = bool(market_data_cfg.get("dynamic_tiering_enabled", False))
    promoted_symbols: list[str] = []
    if dynamic_tiering_enabled and inactive_tier_symbols:
        promotion_count = _as_positive_int(
            market_data_cfg.get("dynamic_tier_promotion_count"),
            4,
        )
        ranked_inactive = _strategy_priority_rank(cfg, _normalize_symbols(inactive_tier_symbols))
        promoted_symbols = ranked_inactive[:promotion_count]
    return _normalize_symbols(base_symbols + promoted_symbols + open_symbols)


def _as_positive_float(value, default: float) -> float:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return default
    if parsed <= 0:
        return default
    return parsed


def _as_positive_int(value, default: int) -> int:
    try:
        parsed = int(float(value))
    except (TypeError, ValueError):
        return default
    if parsed <= 0:
        return default
    return parsed


def _polling_settings(cfg: dict) -> dict:
    market_data_cfg = cfg.get("market_data", {})
    if not isinstance(market_data_cfg, dict):
        market_data_cfg = {}

    fast = _as_positive_float(
        market_data_cfg.get("fast_poll_seconds"),
        DEFAULT_FAST_POLL_SECONDS,
    )
    mid = _as_positive_float(
        market_data_cfg.get("mid_poll_seconds"),
        DEFAULT_MID_POLL_SECONDS,
    )
    slow = _as_positive_float(
        market_data_cfg.get("slow_poll_seconds"),
        DEFAULT_SLOW_POLL_SECONDS,
    )
    if mid < fast:
        mid = fast
    if slow < mid:
        slow = mid

    return {
        "fast_poll_seconds": fast,
        "mid_poll_seconds": mid,
        "slow_poll_seconds": slow,
        "top_opportunity_count": _as_positive_int(
            market_data_cfg.get("top_opportunity_count"),
            DEFAULT_TOP_OPPORTUNITY_COUNT,
        ),
        "mid_tier_count": _as_positive_int(
            market_data_cfg.get("mid_tier_count"),
            DEFAULT_MID_TIER_COUNT,
        ),
        "max_symbols_per_cycle": _as_positive_int(
            market_data_cfg.get("max_symbols_per_cycle"),
            DEFAULT_MAX_SYMBOLS_PER_CYCLE,
        ),
        "watchlist_poll_seconds": _as_positive_float(
            market_data_cfg.get("watchlist_poll_seconds"),
            DEFAULT_WATCHLIST_POLL_SECONDS,
        ),
    }


def _strategy_priority_rank(cfg: dict, symbols: list[str]) -> list[str]:
    if not symbols:
        return []
    state = read_json_file(STATE_DIR / "strategy_state.json", default={})
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
        # Favor symbols with stronger score, then modestly favor higher volatility.
        return score + (volatility * 10_000.0)

    return sorted(symbols, key=lambda symbol: (_score(symbol), symbol), reverse=True)


def _build_symbol_poll_intervals(
    cfg: dict,
    scan_symbols: list[str],
    open_symbols: list[str],
) -> dict[str, float]:
    settings = _polling_settings(cfg)
    configured_symbols = _normalize_symbols(cfg.get("symbols", []))
    priority_rank = _strategy_priority_rank(cfg, configured_symbols)
    open_set = set(_normalize_symbols(open_symbols))

    top_symbols = [
        symbol
        for symbol in priority_rank
        if symbol not in open_set
    ][: settings["top_opportunity_count"]]
    top_set = set(top_symbols)

    mid_candidates = [
        symbol
        for symbol in priority_rank
        if symbol not in open_set and symbol not in top_set
    ][: settings["mid_tier_count"]]
    mid_set = set(mid_candidates)

    intervals: dict[str, float] = {}
    for symbol in scan_symbols:
        if symbol in open_set or symbol in top_set:
            intervals[symbol] = settings["fast_poll_seconds"]
        elif symbol in mid_set:
            intervals[symbol] = settings["mid_poll_seconds"]
        else:
            intervals[symbol] = settings["slow_poll_seconds"]
        watch_until = float(_symbol_watchlist_until.get(symbol, 0.0))
        if symbol not in open_set and watch_until > time.time():
            intervals[symbol] = max(intervals[symbol], settings["watchlist_poll_seconds"])
    return intervals


def _is_symbol_watchlisted(symbol: str, now_epoch: float) -> bool:
    return float(_symbol_watchlist_until.get(symbol, 0.0)) > float(now_epoch)


def _symbol_health_assessment(symbol: str, market: dict, cfg: dict) -> tuple[float, list[str]]:
    market_data_cfg = cfg.get("market_data", {})
    if not isinstance(market_data_cfg, dict):
        market_data_cfg = {}
    score = 100.0
    reasons: list[str] = []
    quality_status = str(market.get("data_quality_status") or "UNKNOWN").upper()
    if quality_status == "GOOD":
        pass
    elif quality_status == "PARTIAL":
        score -= 25.0
        reasons.append("quality_partial")
    elif quality_status == "STALE":
        score -= 45.0
        reasons.append("quality_stale")
    elif quality_status == "INSUFFICIENT":
        score -= 55.0
        reasons.append("quality_insufficient")
    elif quality_status == "UNSUPPORTED_WINDOW":
        score -= 70.0
        reasons.append("quality_unsupported")
    else:
        score -= 20.0
        reasons.append("quality_unknown")

    max_spread_bps = _as_positive_float(
        market_data_cfg.get("max_spread_bps"),
        150.0,
    )
    spread_bps = _as_positive_float(market.get("spread_bps"), 0.0)
    if spread_bps > max_spread_bps:
        penalty = min(30.0, (spread_bps - max_spread_bps) * 0.25)
        score -= penalty
        reasons.append("spread_wide")

    readiness = market.get("core_candle_readiness", {})
    if isinstance(readiness, dict) and not bool(readiness.get("ready", True)):
        score -= 35.0
        reasons.append("core_not_ready")

    score = max(0.0, min(100.0, score))
    return score, reasons


def _update_symbol_health(symbol: str, market: dict, cfg: dict, now_epoch: float) -> dict:
    market_data_cfg = cfg.get("market_data", {})
    if not isinstance(market_data_cfg, dict):
        market_data_cfg = {}
    score, reasons = _symbol_health_assessment(symbol, market, cfg)
    _symbol_health_score[symbol] = score
    min_score = _as_positive_float(
        market_data_cfg.get("symbol_health_min_score"),
        DEFAULT_SYMBOL_HEALTH_MIN_SCORE,
    )
    watchlist_seconds = _as_positive_int(
        market_data_cfg.get("symbol_health_watchlist_seconds"),
        DEFAULT_SYMBOL_HEALTH_WATCHLIST_SECONDS,
    )
    watchlisted = False
    if score < min_score:
        _symbol_watchlist_until[symbol] = float(now_epoch) + float(watchlist_seconds)
        watchlisted = True
    elif symbol in _symbol_watchlist_until and _symbol_watchlist_until[symbol] <= float(now_epoch):
        _symbol_watchlist_until.pop(symbol, None)
    return {
        "score": round(score, 2),
        "reasons": reasons,
        "watchlisted": watchlisted or _is_symbol_watchlisted(symbol, now_epoch),
        "watch_until_epoch": _symbol_watchlist_until.get(symbol),
    }


def _to_float(value, fallback: float | None = None) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return fallback


def _normalize_route_key(value: str) -> str:
    return str(value or "").strip().lower()


def _liquidity_tier(market: dict) -> str:
    spread_bps = _as_positive_float(market.get("spread_bps"), 9999.0)
    trade_count = _as_positive_int(market.get("trade_count"), 0)
    if spread_bps <= 20.0 and trade_count >= 25:
        return "HIGH"
    if spread_bps <= 60.0 and trade_count >= 10:
        return "MEDIUM"
    return "LOW"


def _route_confidence_multiplier(cfg: dict, market: dict) -> float:
    market_data_cfg = cfg.get("market_data", {})
    if not isinstance(market_data_cfg, dict):
        market_data_cfg = {}
    tier = _liquidity_tier(market)
    raw = market_data_cfg.get("route_quality_confidence_multiplier_by_liquidity", {})
    if isinstance(raw, dict):
        value = _to_float(raw.get(tier.lower()))
        if value is None:
            value = _to_float(raw.get(tier.upper()))
        if value is not None and value > 0:
            _route_guard_confidence_tier_hits[tier] = int(_route_guard_confidence_tier_hits.get(tier, 0) or 0) + 1
            return float(value)
    defaults = {"HIGH": 1.0, "MEDIUM": 1.05, "LOW": 1.12}
    _route_guard_confidence_tier_hits[tier] = int(_route_guard_confidence_tier_hits.get(tier, 0) or 0) + 1
    return float(defaults[tier])


def _route_exposure_share_pct(route: str, cfg: dict, now_epoch: float) -> float | None:
    try:
        report = load_route_quality_report_cached(state_dir=STATE_DIR, cfg=cfg, now_epoch=now_epoch)
    except Exception:
        return None
    if not isinstance(report, dict):
        return None
    current = report.get("current", {})
    if not isinstance(current, dict):
        return None
    counts = current.get("effective_route_counts", {})
    if not isinstance(counts, dict):
        return None
    total = 0.0
    target = 0.0
    for key, raw in counts.items():
        value = _to_float(raw, 0.0) or 0.0
        if value <= 0:
            continue
        total += value
        if _normalize_route_key(key) == _normalize_route_key(route):
            target += value
    if total <= 0:
        return None
    return (target / total) * 100.0


def _refresh_route_loss_streaks(now_epoch: float) -> dict[str, int]:
    cache = _route_guard_loss_streak_cache
    trades_path = STATE_DIR / "trades.json"
    try:
        mtime = trades_path.stat().st_mtime
    except OSError:
        mtime = None

    if (
        cache.get("mtime") == mtime
        and (float(now_epoch) - float(cache.get("computed_at", 0.0) or 0.0)) <= ROUTE_GUARD_STREAK_CACHE_TTL_SECONDS
        and isinstance(cache.get("streaks"), dict)
    ):
        return cache.get("streaks")  # type: ignore[return-value]

    trades = read_json_file(trades_path, default=[])
    if not isinstance(trades, list):
        trades = []
    sells: list[dict] = []
    for row in trades:
        if not isinstance(row, dict):
            continue
        if str(row.get("side", "")).upper() != "SELL":
            continue
        route = _normalize_route_key(row.get("effective_route") or row.get("effective_strategy") or row.get("route"))
        if not route:
            route = _normalize_route_key(row.get("reason"))
            if "trend_pullback" in route:
                route = "trend_pullback"
            elif "breakout_momentum" in route:
                route = "breakout_momentum"
            elif "volatility_scalper" in route or route.startswith("scalper_"):
                route = "volatility_scalper"
            else:
                route = "mean_reversion"
        pnl = _to_float(row.get("pnl"), None)
        if pnl is None:
            continue
        sells.append({"time": _to_float(row.get("time"), 0.0) or 0.0, "route": route, "pnl": pnl})
    sells.sort(key=lambda item: float(item.get("time", 0.0)), reverse=True)
    streaks: dict[str, int] = {}
    seen_break: set[str] = set()
    for row in sells:
        route = _normalize_route_key(row.get("route"))
        if not route or route in seen_break:
            continue
        pnl = float(row.get("pnl", 0.0))
        if pnl < 0:
            streaks[route] = int(streaks.get(route, 0) or 0) + 1
        else:
            seen_break.add(route)

    cache["mtime"] = mtime
    cache["computed_at"] = float(now_epoch)
    cache["streaks"] = streaks
    return streaks


def _non_mr_route_guard(
    *,
    symbol: str,
    decision: dict,
    market: dict,
    cfg: dict,
    now_epoch: float,
    pressure: dict,
) -> tuple[bool, str | None]:
    market_data_cfg = cfg.get("market_data", {})
    if not isinstance(market_data_cfg, dict):
        market_data_cfg = {}
    if not bool(market_data_cfg.get("route_quality_guard_enabled", True)):
        return True, None

    route = str(decision.get("effective_route") or decision.get("effective_strategy") or "").upper()
    if route in {"", "MEAN_REVERSION", "MEAN_REVERSION_FRIENDLY"}:
        return True, None

    if _is_symbol_watchlisted(symbol, now_epoch):
        return False, "symbol_watchlisted_health_cooldown"

    readiness = market.get("core_candle_readiness", {})
    if isinstance(readiness, dict) and not bool(readiness.get("ready", True)):
        return False, f"core_not_ready:{readiness.get('reason', 'unknown')}"

    confidence = _to_float(
        decision.get("detected_regime_confidence_score")
        or decision.get("detectedRegimeConfidenceScore")
        or decision.get("regime_confidence_score"),
        0.0,
    ) or 0.0
    stability = _to_float(
        decision.get("detected_regime_stability_score")
        or decision.get("detectedRegimeStabilityScore")
        or decision.get("regime_stability_score"),
        0.0,
    ) or 0.0
    persistence = _to_float(
        decision.get("detected_regime_persistence_score")
        or decision.get("detectedRegimePersistenceScore")
        or decision.get("regime_persistence_score"),
        0.0,
    ) or 0.0

    min_conf = _as_positive_float(
        market_data_cfg.get("route_quality_min_confidence"),
        DEFAULT_ROUTE_QUALITY_MIN_CONFIDENCE,
    )
    min_conf *= _route_confidence_multiplier(cfg, market)
    min_stability = _as_positive_float(
        market_data_cfg.get("route_quality_min_stability"),
        DEFAULT_ROUTE_QUALITY_MIN_STABILITY,
    )
    min_persistence = _as_positive_float(
        market_data_cfg.get("route_quality_min_persistence"),
        DEFAULT_ROUTE_QUALITY_MIN_PERSISTENCE,
    )
    if confidence < min_conf:
        return False, "route_quality_low_confidence"
    if stability < min_stability:
        return False, "route_quality_low_stability"
    if persistence < min_persistence:
        return False, "route_quality_low_persistence"

    quality_status = str(
        decision.get("regime_data_quality_status")
        or market.get("data_quality_status")
        or "UNKNOWN"
    ).upper()
    if quality_status in {"STALE", "INSUFFICIENT", "UNSUPPORTED_WINDOW"}:
        return False, "route_quality_bad_data"

    route_key = _normalize_route_key(route)
    per_route_cap_cfg = market_data_cfg.get("route_quality_max_route_share_pct", {})
    if not isinstance(per_route_cap_cfg, dict):
        per_route_cap_cfg = {}
    cap_pct = _to_float(per_route_cap_cfg.get(route_key), None)
    if cap_pct is not None and cap_pct > 0:
        share_pct = _route_exposure_share_pct(route_key, cfg, now_epoch)
        if share_pct is not None and share_pct >= cap_pct:
            _route_guard_cap_hits[route_key] = int(_route_guard_cap_hits.get(route_key, 0) or 0) + 1
            return False, f"route_exposure_cap:{route_key}:{round(share_pct, 2)}"

    streak_cfg = market_data_cfg.get("route_quality_max_consecutive_losses", {})
    if not isinstance(streak_cfg, dict):
        streak_cfg = {}
    cooldown_cfg = market_data_cfg.get("route_quality_cooldown_seconds_after_losses", {})
    if not isinstance(cooldown_cfg, dict):
        cooldown_cfg = {}
    max_losses = _as_positive_int(streak_cfg.get(route_key), 0)
    cooldown_seconds = _as_positive_int(cooldown_cfg.get(route_key), 0)
    cooldown_until = float(_route_guard_cooldown_until.get(route_key, 0.0) or 0.0)
    if cooldown_until > float(now_epoch):
        _route_guard_cooldown_hits[route_key] = int(_route_guard_cooldown_hits.get(route_key, 0) or 0) + 1
        return False, f"route_cooldown_active:{route_key}:{int(cooldown_until - now_epoch)}"
    if max_losses > 0 and cooldown_seconds > 0:
        streaks = _refresh_route_loss_streaks(now_epoch)
        route_streak = int(streaks.get(route_key, 0) or 0)
        if route_streak >= max_losses:
            _route_guard_cooldown_until[route_key] = float(now_epoch) + float(cooldown_seconds)
            _route_guard_cooldown_hits[route_key] = int(_route_guard_cooldown_hits.get(route_key, 0) or 0) + 1
            return False, f"route_cooldown_triggered:{route_key}:{route_streak}"

    max_rate_limited = _as_positive_int(
        market_data_cfg.get("route_quality_max_rate_limited"),
        DEFAULT_ROUTE_QUALITY_MAX_RATE_LIMITED,
    )
    rate_limited_count = _as_positive_int(pressure.get("rate_limited_count"), 0)
    if rate_limited_count > max_rate_limited:
        return False, "route_quality_throttle_pressure"
    return True, None


def _append_decision_audit(
    *,
    symbol: str,
    market: dict,
    decision: dict,
    executed: bool,
    blocked_reason: str | None,
    execution_report: dict | None = None,
):
    execution = execution_report if isinstance(execution_report, dict) else {}
    decision_ts_epoch = _to_float(decision.get("decision_ts_epoch"), None)
    risk_outcome = "passed" if bool(executed) else (f"blocked:{blocked_reason}" if blocked_reason else "not_executed")
    payload = {
        "ts_epoch": time.time(),
        "decision_ts_epoch": decision_ts_epoch,
        "symbol": symbol,
        "action": decision.get("action"),
        "executed": bool(executed),
        "risk_decision_outcome": risk_outcome,
        "blocked_reason": blocked_reason,
        "decision_reason": decision.get("reason"),
        "effective_route": decision.get("effective_route"),
        "effective_strategy": decision.get("effective_strategy"),
        "configured_regime": decision.get("configured_regime"),
        "detected_regime": decision.get("detected_regime"),
        "confidence_score": decision.get("detected_regime_confidence_score"),
        "stability_score": decision.get("detected_regime_stability_score"),
        "persistence_score": decision.get("detected_regime_persistence_score"),
        "fallback_reason": decision.get("fallback_reason"),
        "auto_fallback_reason": decision.get("auto_fallback_reason"),
        "data_quality_status": market.get("data_quality_status"),
        "data_quality_reason": market.get("data_quality_reason"),
        "core_candle_readiness": market.get("core_candle_readiness"),
        "spread_bps": market.get("spread_bps"),
        "quoted_mid_price": market.get("mid_price"),
        "quoted_best_bid": market.get("best_bid"),
        "quoted_best_ask": market.get("best_ask"),
        "momentum_norm": market.get("momentum_norm"),
        "rsi": market.get("rsi"),
        "atr_raw": market.get("atr_raw"),
        "price": market.get("price"),
        "expected_edge_bps": decision.get("expected_edge_bps"),
        "expected_hold_seconds": decision.get("expected_hold_seconds"),
        "execution_status": execution.get("status"),
        "execution_reason": execution.get("reason"),
        "execution_fill_reason": execution.get("fill_reason"),
        "execution_liquidity_role": execution.get("liquidity_role"),
        "execution_expected_fill_price": execution.get("expected_fill_price"),
        "execution_fill_price": execution.get("fill_price"),
        "execution_quoted_price": execution.get("quoted_price"),
        "execution_fill_ratio": execution.get("fill_ratio"),
        "execution_fee_usd": execution.get("fee_usd"),
        "execution_slippage_bps": execution.get("slippage_bps"),
        "execution_slippage_usd": execution.get("slippage_usd"),
        "execution_latency_ms": execution.get("latency_ms"),
        "execution_latency_bucket": execution.get("latency_bucket"),
        "execution_timed_out": execution.get("timed_out"),
        "execution_rejected": execution.get("rejected"),
        "execution_position_closed": execution.get("position_closed"),
        "execution_hold_time_seconds": execution.get("hold_time_seconds"),
        "execution_exit_reason": execution.get("exit_reason"),
        "execution_realized_pnl_net_usd": execution.get("realized_pnl_net_usd"),
        "execution_mae_pct": execution.get("mae_pct"),
        "execution_mfe_pct": execution.get("mfe_pct"),
        "execution_realized_pnl_usd": execution.get("realized_pnl_usd"),
    }
    try:
        STATE_DIR.mkdir(parents=True, exist_ok=True)
        with DECISION_AUDIT_PATH.open("a", encoding="utf-8") as fh:
            fh.write(_json_dumps_safe(payload) + "\n")
    except Exception as exc:
        logger.debug(f"Decision audit append failed for {symbol}: {exc}")


def _select_symbols_for_cycle(
    *,
    symbols: list[str],
    now_epoch: float,
    last_polled_at: dict[str, float],
    interval_by_symbol: dict[str, float],
    max_symbols_per_cycle: int,
) -> list[str]:
    due: list[tuple[str, float, float]] = []
    for symbol in symbols:
        interval = float(interval_by_symbol.get(symbol, DEFAULT_SLOW_POLL_SECONDS))
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


def _is_action_enabled(cfg: dict, symbol: str, action: str) -> bool:
    legacy_map = cfg.get("symbol_enabled", {})
    buy_map = cfg.get("symbol_buy_enabled", {})
    sell_map = cfg.get("symbol_sell_enabled", {})

    if not isinstance(legacy_map, dict):
        legacy_map = {}
    if not isinstance(buy_map, dict):
        buy_map = {}
    if not isinstance(sell_map, dict):
        sell_map = {}

    action_key = str(action).upper()
    if action_key == "BUY":
        if symbol in buy_map:
            return buy_map.get(symbol) is not False
    elif action_key == "SELL":
        if symbol in sell_map:
            return sell_map.get(symbol) is not False
    else:
        return True

    # Backward compatibility with old single-toggle config.
    if symbol in legacy_map:
        return legacy_map.get(symbol) is not False

    return True


def _log_sync_diagnostics(sync_summary: dict):
    jobs = sync_summary.get("jobs", [])
    if not isinstance(jobs, list):
        return

    error_rows = [row for row in jobs if isinstance(row, dict) and str(row.get("status", "")).lower() == "error"]
    if error_rows:
        top_rows = error_rows[:3]
        compact = "; ".join(
            f"{row.get('symbol', '?')}:{row.get('timeframe', '?')}:{str(row.get('error', 'unknown'))[:120]}"
            for row in top_rows
        )
        logger.warning(
            "Candle sync errors (top %s/%s): %s",
            len(top_rows),
            len(error_rows),
            compact,
        )

    degraded_rows = [
        row for row in jobs
        if isinstance(row, dict) and str(row.get("status", "")).lower() in {"degraded", "unsupported"}
    ]
    if degraded_rows:
        top_rows = degraded_rows[:3]
        compact = "; ".join(
            f"{row.get('symbol', '?')}:{row.get('timeframe', '?')}:{row.get('source', 'unknown')}:{str(row.get('note', ''))[:320]}"
            for row in top_rows
        )
        logger.info(
            "Candle sync degraded (top %s/%s): %s",
            len(top_rows),
            len(degraded_rows),
            compact,
        )


def _apply_adaptive_sync_request_budget(cfg: dict) -> dict:
    market_data_cfg = cfg.get("market_data", {})
    if not isinstance(market_data_cfg, dict):
        market_data_cfg = {}
        cfg["market_data"] = market_data_cfg

    base_cap = _as_positive_int(market_data_cfg.get("max_sync_requests_per_tick"), 8)
    min_cap = _as_positive_int(market_data_cfg.get("min_sync_requests_per_tick_under_pressure"), 1)
    window_seconds = _as_positive_float(market_data_cfg.get("sync_pressure_window_seconds"), 60.0)
    rate_limit_threshold = _as_positive_int(market_data_cfg.get("sync_pressure_rate_limit_threshold"), 3)
    throttle_sleep_threshold = _as_positive_float(
        market_data_cfg.get("sync_pressure_throttle_sleep_seconds"),
        5.0,
    )
    pressure = get_public_api_health(window_seconds=window_seconds)
    rate_limited_count = int(pressure.get("rate_limited_count", 0) or 0)
    throttle_sleep = float(pressure.get("throttle_sleep_seconds_sum", 0.0) or 0.0)
    under_pressure = (
        rate_limited_count >= rate_limit_threshold
        or throttle_sleep >= throttle_sleep_threshold
    )
    effective_cap = max(min_cap, base_cap // 2) if under_pressure else base_cap
    market_data_cfg["max_sync_requests_per_tick"] = int(effective_cap)
    return {
        "base_cap": int(base_cap),
        "effective_cap": int(effective_cap),
        "under_pressure": bool(under_pressure),
        "window_seconds": float(window_seconds),
        "rate_limit_threshold": int(rate_limit_threshold),
        "throttle_sleep_threshold": float(throttle_sleep_threshold),
        "pressure": pressure,
    }


def _persist_market_sync_health(payload: dict):
    try:
        STATE_DIR.mkdir(parents=True, exist_ok=True)
        line = _json_dumps_safe(payload)
        MARKET_SYNC_HEALTH_PATH.write_text(
            line,
            encoding="utf-8",
        )
        with MARKET_SYNC_HEALTH_HISTORY_PATH.open("a", encoding="utf-8") as fh:
            fh.write(line + "\n")
        return True
    except Exception as exc:
        logger.warning(f"Failed to persist market sync health: {exc}")
        return False


def _market_data_source_policy(cfg: dict) -> dict:
    market_data_cfg = cfg.get("market_data", {})
    if not isinstance(market_data_cfg, dict):
        return {}
    source_map = market_data_cfg.get("source_map", {})
    if not isinstance(source_map, dict):
        return {}

    policy: dict[str, dict] = {}
    for section in ("candles", "orderbook", "tickers"):
        raw = source_map.get(section, {})
        if not isinstance(raw, dict):
            continue
        row = {}
        if "authoritative" in raw:
            row["authoritative"] = str(raw.get("authoritative"))
        for key in (
            "allow_public_fallback",
            "allow_snapshot_fallback",
            "decision_use_public_fallback",
            "decision_use_snapshot_fallback",
        ):
            if key in raw:
                row[key] = bool(raw.get(key))
        if row:
            policy[section] = row
    return policy


def _build_sync_slo(sync_summary: dict, coverage_summary: dict, cfg: dict | None = None) -> dict:
    def _non_negative_int(value, default: int) -> int:
        try:
            parsed = int(float(value))
        except (TypeError, ValueError):
            return default
        return max(0, parsed)

    market_data_cfg = cfg.get("market_data", {}) if isinstance(cfg, dict) else {}
    if not isinstance(market_data_cfg, dict):
        market_data_cfg = {}
    slo_cfg = market_data_cfg.get("freshness_slo", {})
    if not isinstance(slo_cfg, dict):
        slo_cfg = {}

    min_fresh_1h = _non_negative_int(slo_cfg.get("min_fresh_1h"), 1)
    min_fresh_4h = _non_negative_int(slo_cfg.get("min_fresh_4h"), 1)
    min_fresh_24h = _non_negative_int(slo_cfg.get("min_fresh_24h"), 0)
    max_sync_errors = _non_negative_int(slo_cfg.get("max_sync_errors"), 0)
    max_degraded_jobs = _non_negative_int(slo_cfg.get("max_degraded_jobs"), 0)
    min_sync_requests = _non_negative_int(slo_cfg.get("min_sync_requests"), 1)

    fresh_counts = coverage_summary.get("fresh_counts_by_timeframe", {})
    stale_symbol_timeframes = int(coverage_summary.get("stale_symbol_timeframes", 0) or 0)
    errors = int(sync_summary.get("errors", 0) or 0)
    degraded = int(sync_summary.get("degraded", 0) or 0)
    requests = int(sync_summary.get("requests", 0) or 0)
    inserted = int(sync_summary.get("new_inserted", 0) or 0)
    fresh_1h = int(fresh_counts.get("1h", 0) or 0)
    fresh_4h = int(fresh_counts.get("4h", 0) or 0)
    fresh_1d = int(fresh_counts.get("1d", 0) or 0)
    coverage_ok = (
        fresh_1h >= min_fresh_1h
        and fresh_4h >= min_fresh_4h
        and fresh_1d >= min_fresh_24h
    )
    quality_ok = degraded <= max_degraded_jobs and errors <= max_sync_errors
    throughput_ok = requests >= min_sync_requests and inserted >= 0
    status = "OK" if (coverage_ok and quality_ok and throughput_ok) else "DEGRADED"
    return {
        "status": status,
        "coverage_ok": bool(coverage_ok),
        "quality_ok": bool(quality_ok),
        "throughput_ok": bool(throughput_ok),
        "fresh_1h": fresh_1h,
        "fresh_4h": fresh_4h,
        "fresh_24h": fresh_1d,
        "stale_symbol_timeframes": stale_symbol_timeframes,
        "requests": requests,
        "new_inserted": inserted,
        "errors": errors,
        "degraded": degraded,
        "thresholds": {
            "min_fresh_1h": int(min_fresh_1h),
            "min_fresh_4h": int(min_fresh_4h),
            "min_fresh_24h": int(min_fresh_24h),
            "max_sync_errors": int(max_sync_errors),
            "max_degraded_jobs": int(max_degraded_jobs),
            "min_sync_requests": int(min_sync_requests),
        },
    }


def _log_candle_coverage():
    summary = summarize_core_timeframe_coverage()
    status_counts = summary.get("status_counts", {})
    fresh_counts = summary.get("fresh_counts_by_timeframe", {})
    logger.info(
        "Candle coverage: status=%s fresh_1h=%s fresh_4h=%s fresh_24h=%s "
        "stale_symbol_timeframes=%s rows=%s rows_24h=%s",
        status_counts,
        fresh_counts.get("1h", 0),
        fresh_counts.get("4h", 0),
        fresh_counts.get("1d", 0),
        summary.get("stale_symbol_timeframes", 0),
        summary.get("total_rows", 0),
        summary.get("rows_updated_last_24h", 0),
    )


def _signal_confirmation_cycles(cfg: dict) -> int:
    risk_cfg = cfg.get("risk", {})
    if not isinstance(risk_cfg, dict):
        return 1

    try:
        return max(1, int(float(risk_cfg.get("signal_confirmation_cycles", 1))))
    except (TypeError, ValueError):
        return 1


def _check_state_dir_writable(directory: Path):
    marker = directory / f".main_write_probe.{os.getpid()}"
    marker.write_text("ok", encoding="utf-8")
    marker.unlink(missing_ok=True)


def _run_startup_checks() -> dict:
    checks: list[dict] = []
    ok = True

    _seed_required_state_files_from_legacy()

    try:
        STATE_DIR.mkdir(parents=True, exist_ok=True)
        checks.append({"name": "state_dir_exists", "ok": True})
    except Exception as exc:
        checks.append({"name": "state_dir_exists", "ok": False, "detail": str(exc)})
        ok = False

    try:
        _check_state_dir_writable(STATE_DIR)
        checks.append({"name": "state_dir_writable", "ok": True})
    except Exception as exc:
        checks.append({"name": "state_dir_writable", "ok": False, "detail": str(exc)})
        ok = False

    lock_cleanup = cleanup_stale_locks(STATE_DIR)
    checks.append(
        {
            "name": "stale_lock_cleanup",
            "ok": True,
            "removed_count": lock_cleanup.get("removed_count", 0),
        }
    )

    temp_cleanup = cleanup_temp_files(STATE_DIR)
    checks.append(
        {
            "name": "temp_file_cleanup",
            "ok": True,
            "removed_count": temp_cleanup.get("removed_count", 0),
        }
    )

    log_cleanup = cleanup_log_rotations(STATE_DIR)
    checks.append(
        {
            "name": "log_rotation_cleanup",
            "ok": log_cleanup.get("failed_count", 0) == 0,
            "removed_count": log_cleanup.get("removed_count", 0),
            "failed_count": log_cleanup.get("failed_count", 0),
        }
    )

    try:
        cfg = load_config()
        housekeeping = _run_housekeeping(cfg if isinstance(cfg, dict) else {})
        checks.append(
            {
                "name": "housekeeping_cleanup",
                "ok": True,
                "removed_sync_history_lines": housekeeping.get("removed_sync_history_lines", 0),
                "removed_decision_audit_lines": housekeeping.get("removed_decision_audit_lines", 0),
                "removed_snapshots": housekeeping.get("removed_snapshots", 0),
            }
        )
    except Exception as exc:
        checks.append({"name": "housekeeping_cleanup", "ok": False, "detail": str(exc)})
        ok = False

    disk = check_disk_space(STATE_DIR)
    checks.append(
        {
            "name": "disk_space",
            "ok": bool(disk.get("ok", False)),
            "free_mb": disk.get("free_mb"),
            "required_min_free_mb": disk.get("required_min_free_mb"),
        }
    )
    if not disk.get("ok", False):
        ok = False

    timestamp_check = check_timestamp_sanity(STATE_DIR)
    checks.append(
        {
            "name": "timestamp_sanity",
            "ok": bool(timestamp_check.get("ok", False)),
            "future_files": timestamp_check.get("future_files", []),
        }
    )
    if not timestamp_check.get("ok", False):
        ok = False

    for filename in REQUIRED_STATE_FILES:
        path = read_path_with_legacy_fallback(
            STATE_DIR / filename,
            resolve_legacy_state_file(DEFAULT_STATE_DIR, filename),
        )
        exists = path.exists()
        checks.append({"name": f"{filename}_present", "ok": exists})
        if not exists:
            ok = False
            continue
        try:
            read_json_file(path, strict=True)
            checks.append({"name": f"{filename}_json_valid", "ok": True})
        except Exception as exc:
            checks.append({"name": f"{filename}_json_valid", "ok": False, "detail": str(exc)})
            ok = False

    state_validation = validate_state_files(STATE_DIR, strict_files_exist=False)
    checks.append(
        {
            "name": "state_integrity",
            "ok": bool(state_validation.get("ok", False)),
            "error_count": len(state_validation.get("errors", [])),
        }
    )
    if not state_validation.get("ok", False):
        ok = False

    try:
        cfg = load_config()
        checks.append({"name": "config_loadable", "ok": isinstance(cfg, dict)})
        if not isinstance(cfg, dict):
            ok = False
    except Exception as exc:
        checks.append({"name": "config_loadable", "ok": False, "detail": str(exc)})
        ok = False

    return {"ok": ok, "checks": checks}


def _log_startup_checks(result: dict):
    if result.get("ok"):
        logger.info("Startup checks passed")
        return
    logger.warning(f"Startup checks reported issues: {result.get('checks', [])}")


def main():
    restart_cause = os.getenv("REVBOT_RESTART_CAUSE", "manual").strip() or "manual"

    try:
        snapshot_path = create_state_snapshot(reason="bot_prestart", state_dir=STATE_DIR)
        logger.info(f"Bot pre-start snapshot: {snapshot_path}")
    except Exception as exc:
        logger.warning(f"Bot pre-start snapshot failed: {exc}")

    try:
        daily_snapshot = ensure_daily_snapshot(
            reason="daily_bot_prestart",
            state_dir=STATE_DIR,
        )
        if daily_snapshot is not None:
            logger.info(f"Bot daily snapshot created: {daily_snapshot}")
    except Exception as exc:
        logger.warning(f"Bot daily snapshot failed: {exc}")

    logger.info("RevBot starting (paper mode default)")
    startup = _run_startup_checks()
    _log_startup_checks(startup)
    append_runtime_event(
        "process_start",
        service="bot",
        restart_cause=restart_cause,
        startup_ok=bool(startup.get("ok", False)),
    )
    if not startup.get("ok", False) and STRICT_STARTUP_CHECKS:
        append_runtime_event(
            "startup_failed",
            service="bot",
            checks=startup.get("checks", []),
        )
        raise RuntimeError("Startup checks failed and strict mode is enabled")

    executor: Executor | None = None
    last_heartbeat = 0.0
    last_account_sync_at = 0.0
    last_universe_sync_at = 0.0
    last_coverage_log_at = 0.0
    last_db_maintenance_at = 0.0
    last_housekeeping_at = 0.0
    symbol_last_polled_at: dict[str, float] = {}
    clean_shutdown = False
    shutdown_reason = "unknown"

    try:
        while True:
            try:
                cfg = load_config()
                now = time.time()

                last_account_sync_at = run_account_sync_if_due(
                    now_epoch=now,
                    last_run_at=last_account_sync_at,
                    interval_seconds=ACCOUNT_SYNC_INTERVAL_SECONDS,
                    sync_fn=sync_account_snapshot,
                    logger=logger,
                )

                last_universe_sync_at = run_universe_sync_if_due(
                    now_epoch=now,
                    last_run_at=last_universe_sync_at,
                    interval_seconds=UNIVERSE_SYNC_INTERVAL_SECONDS,
                    sync_fn=lambda: build_universe_snapshot(cfg),
                    logger=logger,
                )

                if cfg.get("emergency_stop", False):
                    logger.warning("Emergency stop active - waiting for START command")
                    time.sleep(2)
                    continue

                if not cfg.get("enabled", False):
                    logger.info("Bot process disabled - waiting")
                    time.sleep(5)
                    continue

                trading_enabled = bool(cfg.get("trading_enabled", False))

                if executor is None:
                    executor = Executor(cfg)
                else:
                    executor.update_config(cfg)

                executor.enforce_daily_loss_controls(snapshot_fetcher=fetch_market_snapshot)

                now = time.time()
                last_heartbeat = log_heartbeat_if_due(
                    now_epoch=now,
                    last_heartbeat_at=last_heartbeat,
                    heartbeat_interval_seconds=HEARTBEAT_INTERVAL,
                    logger=logger,
                )
                last_coverage_log_at = run_coverage_log_if_due(
                    now_epoch=now,
                    last_run_at=last_coverage_log_at,
                    interval_seconds=COVERAGE_LOG_INTERVAL_SECONDS,
                    log_fn=_log_candle_coverage,
                )
                db_maintenance_interval = _as_positive_int(
                    cfg.get("market_data", {}).get("db_maintenance_interval_seconds", 6 * 60 * 60),
                    6 * 60 * 60,
                ) if isinstance(cfg.get("market_data", {}), dict) else (6 * 60 * 60)
                housekeeping_interval = _as_positive_int(
                    cfg.get("market_data", {}).get("housekeeping_interval_seconds", 60 * 60),
                    60 * 60,
                ) if isinstance(cfg.get("market_data", {}), dict) else (60 * 60)
                last_db_maintenance_at = run_db_maintenance_if_due(
                    now_epoch=now,
                    last_run_at=last_db_maintenance_at,
                    interval_seconds=db_maintenance_interval,
                    maintenance_fn=lambda: run_db_maintenance(cfg=cfg),
                    logger=logger,
                )
                last_housekeeping_at = run_housekeeping_if_due(
                    now_epoch=now,
                    last_run_at=last_housekeeping_at,
                    interval_seconds=housekeeping_interval,
                    housekeeping_fn=lambda: _run_housekeeping(cfg),
                    logger=logger,
                )

                symbols = _symbols_for_scan(cfg, executor)
                if not symbols:
                    logger.info("No symbols configured - waiting")
                    time.sleep(max(int(cfg.get("loop_sleep", 10)), 1))
                    continue

                open_symbols = executor.open_symbols() if executor else []
                poll_intervals = _build_symbol_poll_intervals(
                    cfg=cfg,
                    scan_symbols=symbols,
                    open_symbols=open_symbols,
                )
                poll_settings = _polling_settings(cfg)
                cycle_symbols = _select_symbols_for_cycle(
                    symbols=symbols,
                    now_epoch=now,
                    last_polled_at=symbol_last_polled_at,
                    interval_by_symbol=poll_intervals,
                    max_symbols_per_cycle=poll_settings["max_symbols_per_cycle"],
                )
                if not cycle_symbols:
                    time.sleep(max(int(cfg.get("loop_sleep", 10)), 1))
                    continue

                adaptive_budget = _apply_adaptive_sync_request_budget(cfg)
                sync_summary = run_incremental_sync_tick(cfg=cfg, symbols=cycle_symbols, now_epoch=now)
                coverage_summary = summarize_core_timeframe_coverage()
                sync_health_payload = {
                    "ts_epoch": now,
                    "generated_at": _now_utc_iso(),
                    "adaptive_budget": adaptive_budget,
                    "sync": {
                        "enabled": bool(sync_summary.get("enabled", False)),
                        "attempted_jobs": int(sync_summary.get("attempted_jobs", 0) or 0),
                        "requests": int(sync_summary.get("requests", 0) or 0),
                        "inserted": int(sync_summary.get("inserted", 0) or 0),
                        "new_inserted": int(sync_summary.get("new_inserted", 0) or 0),
                        "updated_existing": int(sync_summary.get("updated_existing", 0) or 0),
                        "candidate_new": int(sync_summary.get("candidate_new", 0) or 0),
                        "eligible_closed": int(sync_summary.get("eligible_closed", 0) or 0),
                        "skipped_existing": int(sync_summary.get("skipped_existing", 0) or 0),
                        "skipped_partial": int(sync_summary.get("skipped_partial", 0) or 0),
                        "errors": int(sync_summary.get("errors", 0) or 0),
                        "degraded": int(sync_summary.get("degraded", 0) or 0),
                    },
                    "coverage": {
                        "status_counts": coverage_summary.get("status_counts", {}),
                        "fresh_counts_by_timeframe": coverage_summary.get("fresh_counts_by_timeframe", {}),
                        "stale_symbol_timeframes": int(coverage_summary.get("stale_symbol_timeframes", 0) or 0),
                        "total_rows": int(coverage_summary.get("total_rows", 0) or 0),
                        "rows_updated_last_24h": int(coverage_summary.get("rows_updated_last_24h", 0) or 0),
                    },
                    "endpoint_telemetry": get_candle_fetch_telemetry(),
                    "source_policy": _market_data_source_policy(cfg),
                    "route_guard": {
                        "exposure_cap_hits": dict(_route_guard_cap_hits),
                        "cooldown_hits": dict(_route_guard_cooldown_hits),
                        "confidence_tier_hits": dict(_route_guard_confidence_tier_hits),
                        "cooldown_until_epoch": dict(_route_guard_cooldown_until),
                    },
                }
                sync_health_payload["slo"] = _build_sync_slo(sync_summary, coverage_summary, cfg)
                _persist_market_sync_health(sync_health_payload)
                if sync_summary.get("enabled") and (
                    int(sync_summary.get("requests", 0) or 0) > 0
                    or int(sync_summary.get("errors", 0) or 0) > 0
                    or int(sync_summary.get("degraded", 0) or 0) > 0
                ):
                    logger.info(
                        "Candle incremental sync: "
                        f"cap={adaptive_budget.get('effective_cap', 0)}/{adaptive_budget.get('base_cap', 0)} "
                        f"pressure_rl={adaptive_budget.get('pressure', {}).get('rate_limited_count', 0)} "
                        f"pressure_sleep_s={round(float(adaptive_budget.get('pressure', {}).get('throttle_sleep_seconds_sum', 0.0) or 0.0), 2)} "
                        f"requests={sync_summary.get('requests', 0)} "
                        f"inserted={sync_summary.get('inserted', 0)} "
                        f"new_inserted={sync_summary.get('new_inserted', 0)} "
                        f"updated_existing={sync_summary.get('updated_existing', 0)} "
                        f"candidate_new={sync_summary.get('candidate_new', 0)} "
                        f"eligible_closed={sync_summary.get('eligible_closed', 0)} "
                        f"skipped_existing={sync_summary.get('skipped_existing', 0)} "
                        f"skipped_partial={sync_summary.get('skipped_partial', 0)} "
                        f"errors={sync_summary.get('errors', 0)} "
                        f"degraded={sync_summary.get('degraded', 0)}"
                    )
                    _log_sync_diagnostics(sync_summary)

                for symbol in cycle_symbols:
                    market = fetch_market_snapshot(symbol, cfg)
                    if market is None:
                        continue
                    health = _update_symbol_health(symbol, market, cfg, now)
                    if health.get("watchlisted") and health.get("reasons"):
                        logger.info(
                            f"{symbol} health watchlist | score={health.get('score')} "
                            f"reasons={','.join(health.get('reasons', []))}"
                        )

                    decision_context = build_decision_context(market, cfg)
                    append_replay_event(
                        "decision_context",
                        {
                            "symbol": decision_context.symbol,
                            "allowed": decision_context.allowed,
                            "blocked_reason": decision_context.blocked_reason,
                            "audit": decision_context.audit,
                        },
                        cfg,
                    )
                    if decision_context.allowed and isinstance(decision_context.strategy_input, dict):
                        decision = evaluate_symbol(decision_context.strategy_input, cfg)
                    else:
                        reason = decision_context.blocked_reason or "market_eval_gate_blocked"
                        logger.info(f"{symbol} -> HOLD | reason={reason}")
                        decision = {
                            "symbol": symbol,
                            "action": "HOLD",
                            "reason": reason,
                        }
                    action = decision.get("action")
                    executed = False
                    blocked_reason = None
                    execution_report = None
                    if action != "HOLD":
                        if action == "BUY" and not trading_enabled:
                            logger.info(
                                f"{symbol} -> BUY blocked (trading disabled)"
                            )
                            blocked_reason = "trading_disabled"
                            _append_decision_audit(
                                symbol=symbol,
                                market=market,
                                decision=decision,
                                executed=executed,
                                blocked_reason=blocked_reason,
                                execution_report=execution_report,
                            )
                            time.sleep(0.2)
                            continue

                        if action == "BUY":
                            required_cycles = _signal_confirmation_cycles(cfg)
                            streak = _buy_signal_streak.get(symbol, 0) + 1
                            _buy_signal_streak[symbol] = streak
                            if streak < required_cycles:
                                logger.info(
                                    f"{symbol} -> BUY blocked "
                                    f"(signal confirmation {streak}/{required_cycles})"
                                )
                                blocked_reason = "signal_confirmation"
                                _append_decision_audit(
                                    symbol=symbol,
                                    market=market,
                                    decision=decision,
                                    executed=executed,
                                    blocked_reason=blocked_reason,
                                    execution_report=execution_report,
                                )
                                time.sleep(0.2)
                                continue
                            guard_ok, guard_reason = _non_mr_route_guard(
                                symbol=symbol,
                                decision=decision,
                                market=market,
                                cfg=cfg,
                                now_epoch=now,
                                pressure=adaptive_budget.get("pressure", {}),
                            )
                            if not guard_ok:
                                logger.info(f"{symbol} -> BUY blocked ({guard_reason})")
                                blocked_reason = str(guard_reason or "route_guard")
                                _append_decision_audit(
                                    symbol=symbol,
                                    market=market,
                                    decision=decision,
                                    executed=executed,
                                    blocked_reason=blocked_reason,
                                    execution_report=execution_report,
                                )
                                time.sleep(0.2)
                                continue
                        else:
                            _buy_signal_streak.pop(symbol, None)

                        if not _is_action_enabled(cfg, symbol, action):
                            logger.info(
                                f"{symbol} -> {action} blocked (symbol {action} toggle off)"
                            )
                            blocked_reason = f"{action.lower()}_toggle_off"
                            _append_decision_audit(
                                symbol=symbol,
                                market=market,
                                decision=decision,
                                executed=executed,
                                blocked_reason=blocked_reason,
                                execution_report=execution_report,
                            )
                            time.sleep(0.2)
                            continue
                        executed = bool(executor.handle_decision(decision, market=market))
                        execution_report = (
                            executor.last_execution_report
                            if isinstance(getattr(executor, "last_execution_report", None), dict)
                            else None
                        )
                    else:
                        _buy_signal_streak.pop(symbol, None)

                    _append_decision_audit(
                        symbol=symbol,
                        market=market,
                        decision=decision,
                        executed=executed,
                        blocked_reason=blocked_reason,
                        execution_report=execution_report,
                    )
                    time.sleep(0.2)

                time.sleep(max(int(cfg.get("loop_sleep", 10)), 1))
            except Exception as exc:
                append_runtime_event(
                    "main_loop_error",
                    service="bot",
                    error=str(exc),
                )
                logger.exception(f"Main loop error: {exc}")
                time.sleep(5)
    except KeyboardInterrupt:
        clean_shutdown = True
        shutdown_reason = "keyboard_interrupt"
        logger.info("Shutdown requested by keyboard interrupt")
    except SystemExit:
        clean_shutdown = True
        shutdown_reason = "system_exit"
        logger.info("Shutdown requested by system exit")
        raise
    finally:
        append_runtime_event(
            "process_exit",
            service="bot",
            clean_shutdown=clean_shutdown,
            reason=shutdown_reason,
            ended_at_utc=_now_utc_iso(),
        )
        logging.shutdown()


if __name__ == "__main__":
    main()
