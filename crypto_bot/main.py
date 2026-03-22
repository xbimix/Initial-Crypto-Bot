import time
import os
import logging
from datetime import datetime, timezone
from pathlib import Path

from api.revolut_account_sync import sync_account_snapshot
from api.revolut_universe import build_universe_snapshot
from data.candle_coverage import summarize_core_timeframe_coverage
from data.live_sync_scheduler import run_incremental_sync_tick
from data.market_data import fetch_market_snapshot
from strategy.strategy_engine import evaluate_symbol
from trading.executor import Executor
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
from utils.state_io import read_json_file
from utils.state_snapshot import create_state_snapshot, ensure_daily_snapshot
from utils.state_validator import validate_state_files

logger = setup_logger("main")

HEARTBEAT_INTERVAL = 60
ACCOUNT_SYNC_INTERVAL_SECONDS = 120
UNIVERSE_SYNC_INTERVAL_SECONDS = 300
COVERAGE_LOG_INTERVAL_SECONDS = 300
_buy_signal_streak: dict[str, int] = {}
DEFAULT_FAST_POLL_SECONDS = 20.0
DEFAULT_MID_POLL_SECONDS = 90.0
DEFAULT_SLOW_POLL_SECONDS = 240.0
DEFAULT_TOP_OPPORTUNITY_COUNT = 12
DEFAULT_MID_TIER_COUNT = 28
DEFAULT_MAX_SYMBOLS_PER_CYCLE = 16
STATE_DIR = Path(__file__).resolve().parent / "state"
REQUIRED_STATE_FILES = (
    "config.json",
    "paper_state.json",
    "strategy_state.json",
    "trades.json",
)


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

    base_symbols = tiered_symbols or configured_symbols
    open_symbols = executor.open_symbols() if executor else []
    return _normalize_symbols(base_symbols + open_symbols)


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
    return intervals


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
        path = STATE_DIR / filename
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
    symbol_last_polled_at: dict[str, float] = {}
    clean_shutdown = False
    shutdown_reason = "unknown"

    try:
        while True:
            try:
                cfg = load_config()
                now = time.time()

                if (now - last_account_sync_at) >= ACCOUNT_SYNC_INTERVAL_SECONDS:
                    try:
                        account_snapshot = sync_account_snapshot()
                        logger.info(
                            "Revolut account sync: "
                            f"status={account_snapshot.get('sync_status', 'unknown')} "
                            f"assets={account_snapshot.get('asset_count', 0)}"
                        )
                    except Exception as exc:
                        logger.warning(f"Revolut account sync failed: {exc}")
                    finally:
                        last_account_sync_at = now

                if (now - last_universe_sync_at) >= UNIVERSE_SYNC_INTERVAL_SECONDS:
                    try:
                        universe_snapshot = build_universe_snapshot(cfg)
                        universe_summary = universe_snapshot.get("summary", {})
                        logger.info(
                            "Revolut universe sync: "
                            f"symbols={universe_summary.get('total_symbols', 0)} "
                            f"eligible={universe_summary.get('eligible_count', 0)} "
                            f"tracked={universe_summary.get('tracked_count', 0)}"
                        )
                    except Exception as exc:
                        logger.warning(f"Revolut universe sync failed: {exc}")
                    finally:
                        last_universe_sync_at = now

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
                if now - last_heartbeat > HEARTBEAT_INTERVAL:
                    logger.info("Heartbeat - bot running")
                    last_heartbeat = now
                if (now - last_coverage_log_at) >= COVERAGE_LOG_INTERVAL_SECONDS:
                    _log_candle_coverage()
                    last_coverage_log_at = now

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

                sync_summary = run_incremental_sync_tick(cfg=cfg, symbols=cycle_symbols, now_epoch=now)
                if sync_summary.get("enabled") and (
                    int(sync_summary.get("requests", 0) or 0) > 0
                    or int(sync_summary.get("errors", 0) or 0) > 0
                    or int(sync_summary.get("degraded", 0) or 0) > 0
                ):
                    logger.info(
                        "Candle incremental sync: "
                        f"requests={sync_summary.get('requests', 0)} "
                        f"inserted={sync_summary.get('inserted', 0)} "
                        f"errors={sync_summary.get('errors', 0)} "
                        f"degraded={sync_summary.get('degraded', 0)}"
                    )
                    _log_sync_diagnostics(sync_summary)

                for symbol in cycle_symbols:
                    market = fetch_market_snapshot(symbol, cfg)
                    if market is None:
                        continue

                    decision = evaluate_symbol(market, cfg)
                    action = decision.get("action")
                    if action != "HOLD":
                        if action == "BUY" and not trading_enabled:
                            logger.info(
                                f"{symbol} -> BUY blocked (trading disabled)"
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
                                time.sleep(0.2)
                                continue
                        else:
                            _buy_signal_streak.pop(symbol, None)

                        if not _is_action_enabled(cfg, symbol, action):
                            logger.info(
                                f"{symbol} -> {action} blocked (symbol {action} toggle off)"
                            )
                            time.sleep(0.2)
                            continue
                        executor.handle_decision(decision)
                    else:
                        _buy_signal_streak.pop(symbol, None)

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
