from __future__ import annotations

import time
from collections.abc import Callable
from typing import Any


def log_heartbeat_if_due(
    *,
    now_epoch: float,
    last_heartbeat_at: float,
    heartbeat_interval_seconds: float,
    logger,
) -> float:
    if (now_epoch - last_heartbeat_at) <= heartbeat_interval_seconds:
        return last_heartbeat_at
    logger.info("Heartbeat - bot running")
    return now_epoch


def run_account_sync_if_due(
    *,
    now_epoch: float,
    last_run_at: float,
    interval_seconds: float,
    sync_fn: Callable[[], dict[str, Any]],
    logger,
) -> float:
    if (now_epoch - last_run_at) < interval_seconds:
        return last_run_at
    try:
        account_snapshot = sync_fn()
        logger.info(
            "Revolut account sync: "
            f"status={account_snapshot.get('sync_status', 'unknown')} "
            f"assets={account_snapshot.get('asset_count', 0)}"
        )
    except Exception as exc:
        logger.warning(f"Revolut account sync failed: {exc}")
    return now_epoch


def run_universe_sync_if_due(
    *,
    now_epoch: float,
    last_run_at: float,
    interval_seconds: float,
    sync_fn: Callable[[], dict[str, Any]],
    logger,
) -> float:
    if (now_epoch - last_run_at) < interval_seconds:
        return last_run_at
    try:
        universe_snapshot = sync_fn()
        universe_summary = universe_snapshot.get("summary", {})
        logger.info(
            "Revolut universe sync: "
            f"symbols={universe_summary.get('total_symbols', 0)} "
            f"eligible={universe_summary.get('eligible_count', 0)} "
            f"tracked={universe_summary.get('tracked_count', 0)}"
        )
    except Exception as exc:
        logger.warning(f"Revolut universe sync failed: {exc}")
    return now_epoch


def run_coverage_log_if_due(
    *,
    now_epoch: float,
    last_run_at: float,
    interval_seconds: float,
    log_fn: Callable[[], None],
) -> float:
    if (now_epoch - last_run_at) < interval_seconds:
        return last_run_at
    log_fn()
    return now_epoch


def run_db_maintenance_if_due(
    *,
    now_epoch: float,
    last_run_at: float,
    interval_seconds: float,
    maintenance_fn: Callable[[], dict[str, Any]],
    logger,
) -> float:
    if (now_epoch - last_run_at) < interval_seconds:
        return last_run_at
    try:
        maintenance = maintenance_fn()
        logger.info(
            "DB maintenance: "
            f"trimmed_rows={maintenance.get('trimmed_rows', 0)} "
            f"rows_after={maintenance.get('rows_after', 0)} "
            f"duration_ms={maintenance.get('duration_ms', 0)}"
        )
    except Exception as exc:
        logger.warning(f"DB maintenance failed: {exc}")
    return now_epoch


def run_housekeeping_if_due(
    *,
    now_epoch: float,
    last_run_at: float,
    interval_seconds: float,
    housekeeping_fn: Callable[[], dict[str, Any]],
    logger,
) -> float:
    if (now_epoch - last_run_at) < interval_seconds:
        return last_run_at
    try:
        housekeeping = housekeeping_fn()
        if any(int(housekeeping.get(key, 0) or 0) > 0 for key in housekeeping):
            logger.info(
                "Housekeeping: "
                f"sync_history_lines={housekeeping.get('removed_sync_history_lines', 0)} "
                f"audit_lines={housekeeping.get('removed_decision_audit_lines', 0)} "
                f"snapshots={housekeeping.get('removed_snapshots', 0)}"
            )
    except Exception as exc:
        logger.warning(f"Housekeeping failed: {exc}")
    return now_epoch


def now_epoch() -> float:
    return time.time()
