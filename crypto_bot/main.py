import time
import os
import logging
from datetime import datetime, timezone
from pathlib import Path

from api.revolut_account_sync import sync_account_snapshot
from api.revolut_universe import build_universe_snapshot
from data.market_data import fetch_market_snapshot
from strategy.strategy_engine import evaluate_symbol
from trading.executor import Executor
from utils.config_loader import load_config
from utils.logger import setup_logger
from utils.runtime_events import append_runtime_event
from utils.runtime_guard import (
    check_disk_space,
    check_timestamp_sanity,
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
_buy_signal_streak: dict[str, int] = {}
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
    configured_symbols = _normalize_symbols(cfg.get("symbols", []))
    open_symbols = executor.open_symbols() if executor else []
    return _normalize_symbols(configured_symbols + open_symbols)


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

                symbols = _symbols_for_scan(cfg, executor)
                if not symbols:
                    logger.info("No symbols configured - waiting")
                    time.sleep(max(int(cfg.get("loop_sleep", 10)), 1))
                    continue

                for symbol in symbols:
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
