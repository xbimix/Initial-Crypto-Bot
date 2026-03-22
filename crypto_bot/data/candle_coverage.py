from __future__ import annotations

import sqlite3
import time
from pathlib import Path
from typing import Any

DEFAULT_DB_PATH = Path(__file__).resolve().parent.parent / "state" / "market_data.db"

_INTERVAL_MS = {
    "1m": 60_000,
    "5m": 300_000,
    "15m": 900_000,
    "30m": 1_800_000,
    "1h": 3_600_000,
    "4h": 14_400_000,
    "1d": 86_400_000,
}


def summarize_core_timeframe_coverage(
    *,
    db_path: str | Path | None = None,
    now_ms: int | None = None,
    stale_intervals: int = 3,
    core_timeframes: tuple[str, ...] = ("1h", "4h", "1d"),
) -> dict[str, Any]:
    path = Path(db_path) if db_path is not None else DEFAULT_DB_PATH
    now = int(now_ms if now_ms is not None else time.time() * 1000)

    summary: dict[str, Any] = {
        "db_path": str(path),
        "now_ms": now,
        "stale_intervals": int(max(1, stale_intervals)),
        "status_counts": {},
        "fresh_symbols_by_timeframe": {},
        "fresh_counts_by_timeframe": {},
        "stale_symbol_timeframes": 0,
        "total_rows": 0,
        "rows_updated_last_1h": 0,
        "rows_updated_last_24h": 0,
    }

    if not path.exists():
        summary["error"] = "db_missing"
        return summary

    with sqlite3.connect(str(path)) as conn:
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()
        tables = {
            row[0]
            for row in cur.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            ).fetchall()
        }
        if "sync_state" in tables:
            for row in cur.execute(
                "SELECT lower(coalesce(status,'unknown')) AS status, count(*) AS c "
                "FROM sync_state GROUP BY lower(coalesce(status,'unknown'))"
            ):
                summary["status_counts"][row["status"]] = int(row["c"])

        if "candles" not in tables:
            return summary

        summary["total_rows"] = int(cur.execute("SELECT COUNT(*) FROM candles").fetchone()[0])
        summary["rows_updated_last_1h"] = int(
            cur.execute("SELECT COUNT(*) FROM candles WHERE updated_at >= ?", (now - 3_600_000,)).fetchone()[0]
        )
        summary["rows_updated_last_24h"] = int(
            cur.execute("SELECT COUNT(*) FROM candles WHERE updated_at >= ?", (now - 86_400_000,)).fetchone()[0]
        )

        latest_rows = cur.execute(
            "SELECT symbol, timeframe, MAX(open_time) AS latest_open_time "
            "FROM candles GROUP BY symbol, timeframe"
        ).fetchall()
        stale_count = 0
        fresh_by_tf: dict[str, set[str]] = {tf: set() for tf in core_timeframes}
        for row in latest_rows:
            tf = str(row["timeframe"])
            latest_open = int(row["latest_open_time"] or 0)
            interval_ms = _INTERVAL_MS.get(tf)
            if interval_ms is None:
                continue
            is_stale = (now - latest_open) > (interval_ms * int(max(1, stale_intervals)))
            if is_stale:
                stale_count += 1
            if tf in fresh_by_tf and not is_stale:
                fresh_by_tf[tf].add(str(row["symbol"]))

        summary["stale_symbol_timeframes"] = stale_count
        for tf, symbols in fresh_by_tf.items():
            ordered = sorted(symbols)
            summary["fresh_symbols_by_timeframe"][tf] = ordered
            summary["fresh_counts_by_timeframe"][tf] = len(ordered)

    return summary
