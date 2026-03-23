from __future__ import annotations

import sqlite3
import time
from pathlib import Path
from typing import Any

from data.revolut_candle_store import RevolutCandleStore
from data.revolut_market_db import resolve_db_path


def _retention_config(cfg: dict[str, Any]) -> dict[str, int]:
    market_data = cfg.get("market_data", {})
    if not isinstance(market_data, dict):
        market_data = {}
    raw = market_data.get("retention_days_by_timeframe", {})
    defaults = {"1m": 14, "5m": 30, "15m": 120, "1h": 365, "4h": 730, "1d": 1460}
    out = dict(defaults)
    if isinstance(raw, dict):
        for tf, days in raw.items():
            key = str(tf or "").strip().lower()
            if not key:
                continue
            try:
                parsed = int(float(days))
            except (TypeError, ValueError):
                continue
            if parsed > 0:
                out[key] = parsed
    return out


def run_db_maintenance(*, cfg: dict[str, Any], db_path: str | Path | None = None) -> dict[str, Any]:
    db = resolve_db_path(db_path)
    store = RevolutCandleStore(db)
    started_ms = int(time.time() * 1000)

    retention = _retention_config(cfg)
    trimmed = 0
    for tf, days in retention.items():
        # Trim across all symbols for a timeframe.
        with sqlite3.connect(db) as conn:
            symbols = [row[0] for row in conn.execute("SELECT DISTINCT symbol FROM candles WHERE timeframe = ?", (tf,))]
        for symbol in symbols:
            try:
                trimmed += int(store.trim_to_lookback_days(symbol=symbol, timeframe=tf, lookback_days=days) or 0)
            except Exception:
                continue

    with sqlite3.connect(db) as conn:
        conn.execute("PRAGMA optimize;")
        conn.execute("ANALYZE;")
        conn.execute("VACUUM;")
        rows = int(conn.execute("SELECT COUNT(*) FROM candles").fetchone()[0])
    ended_ms = int(time.time() * 1000)
    return {
        "started_at_ms": started_ms,
        "ended_at_ms": ended_ms,
        "duration_ms": max(0, ended_ms - started_ms),
        "trimmed_rows": int(trimmed),
        "rows_after": rows,
        "retention_days_by_timeframe": retention,
        "db_path": str(db),
    }

