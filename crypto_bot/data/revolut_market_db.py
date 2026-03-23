from __future__ import annotations

import sqlite3
import time
from pathlib import Path
from typing import Iterable

from data.revolut_candle_fetcher import timeframe_to_interval_minutes

DEFAULT_DB_PATH = Path(__file__).resolve().parent.parent / "state" / "market_data.db"


def resolve_db_path(db_path: str | Path | None = None) -> Path:
    path = Path(db_path) if db_path is not None else DEFAULT_DB_PATH
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


def connect(db_path: str | Path | None = None) -> sqlite3.Connection:
    conn = sqlite3.connect(str(resolve_db_path(db_path)))
    conn.row_factory = sqlite3.Row
    return conn


def ensure_schema(
    db_path: str | Path | None = None,
    *,
    include_orderbook_snapshots: bool = True,
) -> None:
    with connect(db_path) as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS candles (
                symbol TEXT NOT NULL,
                timeframe TEXT NOT NULL,
                open_time INTEGER NOT NULL,
                close_time INTEGER,
                open REAL NOT NULL,
                high REAL NOT NULL,
                low REAL NOT NULL,
                close REAL NOT NULL,
                volume REAL,
                source TEXT,
                updated_at INTEGER NOT NULL,
                PRIMARY KEY (symbol, timeframe, open_time)
            )
            """
        )
        conn.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_candles_symbol_timeframe_open_time
            ON candles(symbol, timeframe, open_time)
            """
        )
        conn.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_candles_symbol_open_time
            ON candles(symbol, open_time)
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS sync_state (
                symbol TEXT NOT NULL,
                timeframe TEXT NOT NULL,
                earliest_ms INTEGER,
                latest_ms INTEGER,
                last_sync_ms INTEGER,
                status TEXT,
                note TEXT,
                updated_at INTEGER NOT NULL,
                PRIMARY KEY (symbol, timeframe)
            )
            """
        )
        conn.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_sync_state_updated_at
            ON sync_state(updated_at)
            """
        )

        if include_orderbook_snapshots:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS orderbook_snapshots (
                    symbol TEXT NOT NULL,
                    ts INTEGER NOT NULL,
                    best_bid REAL,
                    best_ask REAL,
                    spread REAL,
                    bid_1_price REAL,
                    bid_1_size REAL,
                    bid_2_price REAL,
                    bid_2_size REAL,
                    bid_3_price REAL,
                    bid_3_size REAL,
                    bid_4_price REAL,
                    bid_4_size REAL,
                    bid_5_price REAL,
                    bid_5_size REAL,
                    ask_1_price REAL,
                    ask_1_size REAL,
                    ask_2_price REAL,
                    ask_2_size REAL,
                    ask_3_price REAL,
                    ask_3_size REAL,
                    ask_4_price REAL,
                    ask_4_size REAL,
                    ask_5_price REAL,
                    ask_5_size REAL,
                    source TEXT
                )
                """
            )
            conn.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_orderbook_snapshots_symbol_ts
                ON orderbook_snapshots(symbol, ts)
                """
            )


def upsert_candles(
    symbol: str,
    timeframe: str,
    candles: Iterable[dict],
    *,
    db_path: str | Path | None = None,
    source: str = "revolut",
) -> int:
    rows: list[tuple] = []
    now_ms = int(time.time() * 1000)

    for candle in candles:
        open_time = int(candle["ts"])
        close_time = candle.get("close_time")
        close_time_val = int(close_time) if close_time is not None else None
        volume = candle.get("volume")
        volume_val = float(volume) if volume is not None else None
        rows.append(
            (
                symbol,
                timeframe,
                open_time,
                close_time_val,
                float(candle["open"]),
                float(candle["high"]),
                float(candle["low"]),
                float(candle["close"]),
                volume_val,
                source,
                now_ms,
            )
        )

    if not rows:
        return 0

    ensure_schema(db_path)
    with connect(db_path) as conn:
        conn.executemany(
            """
            INSERT INTO candles (
                symbol, timeframe, open_time, close_time,
                open, high, low, close, volume, source, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(symbol, timeframe, open_time) DO UPDATE SET
                close_time = excluded.close_time,
                open = excluded.open,
                high = excluded.high,
                low = excluded.low,
                close = excluded.close,
                volume = excluded.volume,
                source = excluded.source,
                updated_at = excluded.updated_at
            """,
            rows,
        )
    return len(rows)


def trim_candles_to_limit(
    symbol: str,
    timeframe: str,
    max_rows: int,
    *,
    db_path: str | Path | None = None,
) -> int:
    max_rows = int(max_rows)
    if max_rows <= 0:
        return 0
    ensure_schema(db_path)
    with connect(db_path) as conn:
        deleted = conn.execute(
            """
            DELETE FROM candles
            WHERE symbol = ?
              AND timeframe = ?
              AND open_time NOT IN (
                  SELECT open_time
                  FROM candles
                  WHERE symbol = ? AND timeframe = ?
                  ORDER BY open_time DESC
                  LIMIT ?
              )
            """,
            (symbol, timeframe, symbol, timeframe, max_rows),
        ).rowcount
    return int(deleted or 0)


def trim_candles_to_lookback_days(
    symbol: str,
    timeframe: str,
    lookback_days: int,
    *,
    db_path: str | Path | None = None,
) -> int:
    lookback_days = int(lookback_days)
    if lookback_days <= 0:
        return 0
    interval_minutes = timeframe_to_interval_minutes(timeframe)
    max_rows = int((lookback_days * 24 * 60) / max(interval_minutes, 1)) + 1
    return trim_candles_to_limit(
        symbol=symbol,
        timeframe=timeframe,
        max_rows=max_rows,
        db_path=db_path,
    )


def delete_candles_for_symbol_timeframe(
    symbol: str,
    timeframe: str,
    *,
    db_path: str | Path | None = None,
) -> int:
    ensure_schema(db_path)
    with connect(db_path) as conn:
        deleted = conn.execute(
            """
            DELETE FROM candles
            WHERE symbol = ? AND timeframe = ?
            """,
            (symbol, timeframe),
        ).rowcount
    return int(deleted or 0)


def get_latest_open_time(
    symbol: str,
    timeframe: str,
    *,
    db_path: str | Path | None = None,
) -> int | None:
    ensure_schema(db_path)
    with connect(db_path) as conn:
        row = conn.execute(
            """
            SELECT MAX(open_time) AS max_open_time
            FROM candles
            WHERE symbol = ? AND timeframe = ?
            """,
            (symbol, timeframe),
        ).fetchone()
    if not row or row["max_open_time"] is None:
        return None
    return int(row["max_open_time"])


def get_earliest_open_time(
    symbol: str,
    timeframe: str,
    *,
    db_path: str | Path | None = None,
) -> int | None:
    ensure_schema(db_path)
    with connect(db_path) as conn:
        row = conn.execute(
            """
            SELECT MIN(open_time) AS min_open_time
            FROM candles
            WHERE symbol = ? AND timeframe = ?
            """,
            (symbol, timeframe),
        ).fetchone()
    if not row or row["min_open_time"] is None:
        return None
    return int(row["min_open_time"])


def get_candles(
    symbol: str,
    timeframe: str,
    *,
    db_path: str | Path | None = None,
    limit: int | None = None,
    ascending: bool = True,
) -> list[dict]:
    ensure_schema(db_path)
    order = "ASC" if ascending else "DESC"
    sql = f"""
        SELECT symbol, timeframe, open_time, close_time, open, high, low, close, volume, source, updated_at
        FROM candles
        WHERE symbol = ? AND timeframe = ?
        ORDER BY open_time {order}
    """
    params: list = [symbol, timeframe]
    if limit is not None:
        sql += " LIMIT ?"
        params.append(int(limit))

    with connect(db_path) as conn:
        rows = conn.execute(sql, params).fetchall()
    return [dict(row) for row in rows]


def get_candle_count(
    symbol: str,
    timeframe: str,
    *,
    db_path: str | Path | None = None,
) -> int:
    ensure_schema(db_path)
    with connect(db_path) as conn:
        row = conn.execute(
            """
            SELECT COUNT(*) AS candle_count
            FROM candles
            WHERE symbol = ? AND timeframe = ?
            """,
            (symbol, timeframe),
        ).fetchone()
    return int(row["candle_count"]) if row else 0


def get_last_updated_at(
    symbol: str,
    timeframe: str,
    *,
    db_path: str | Path | None = None,
) -> int | None:
    ensure_schema(db_path)
    with connect(db_path) as conn:
        row = conn.execute(
            """
            SELECT MAX(updated_at) AS max_updated_at
            FROM candles
            WHERE symbol = ? AND timeframe = ?
            """,
            (symbol, timeframe),
        ).fetchone()
    if not row or row["max_updated_at"] is None:
        return None
    return int(row["max_updated_at"])


def get_sync_state(
    symbol: str,
    timeframe: str,
    *,
    db_path: str | Path | None = None,
) -> dict | None:
    ensure_schema(db_path)
    with connect(db_path) as conn:
        row = conn.execute(
            """
            SELECT
                symbol, timeframe, earliest_ms, latest_ms, last_sync_ms, status, note, updated_at
            FROM sync_state
            WHERE symbol = ? AND timeframe = ?
            """,
            (symbol, timeframe),
        ).fetchone()
    return dict(row) if row else None


def upsert_sync_state(
    symbol: str,
    timeframe: str,
    *,
    earliest_ms: int | None,
    latest_ms: int | None,
    last_sync_ms: int | None,
    status: str,
    note: str = "",
    db_path: str | Path | None = None,
) -> None:
    ensure_schema(db_path)
    updated_at = int(time.time() * 1000)
    with connect(db_path) as conn:
        conn.execute(
            """
            INSERT INTO sync_state (
                symbol, timeframe, earliest_ms, latest_ms, last_sync_ms, status, note, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(symbol, timeframe) DO UPDATE SET
                earliest_ms = excluded.earliest_ms,
                latest_ms = excluded.latest_ms,
                last_sync_ms = excluded.last_sync_ms,
                status = excluded.status,
                note = excluded.note,
                updated_at = excluded.updated_at
            """,
            (
                symbol,
                timeframe,
                int(earliest_ms) if earliest_ms is not None else None,
                int(latest_ms) if latest_ms is not None else None,
                int(last_sync_ms) if last_sync_ms is not None else None,
                str(status),
                str(note or ""),
                updated_at,
            ),
        )


def delete_sync_state(
    symbol: str,
    timeframe: str,
    *,
    db_path: str | Path | None = None,
) -> int:
    ensure_schema(db_path)
    with connect(db_path) as conn:
        deleted = conn.execute(
            """
            DELETE FROM sync_state
            WHERE symbol = ? AND timeframe = ?
            """,
            (symbol, timeframe),
        ).rowcount
    return int(deleted or 0)


def find_missing_ranges(
    symbol: str,
    timeframe: str,
    *,
    target_start_ms: int,
    target_end_ms: int,
    db_path: str | Path | None = None,
) -> list[tuple[int, int]]:
    start_ms = int(target_start_ms)
    end_ms = int(target_end_ms)
    if end_ms <= start_ms:
        return []

    interval_ms = timeframe_to_interval_minutes(timeframe) * 60_000
    ensure_schema(db_path)
    with connect(db_path) as conn:
        rows = conn.execute(
            """
            SELECT open_time
            FROM candles
            WHERE symbol = ? AND timeframe = ? AND open_time BETWEEN ? AND ?
            ORDER BY open_time ASC
            """,
            (symbol, timeframe, start_ms, end_ms),
        ).fetchall()

    if not rows:
        return [(start_ms, end_ms)]

    missing: list[tuple[int, int]] = []
    cursor = start_ms
    for row in rows:
        open_time = int(row["open_time"])
        if open_time < cursor:
            continue
        if open_time > cursor:
            gap_end = min(open_time - interval_ms, end_ms)
            if cursor <= gap_end:
                missing.append((cursor, gap_end))
        cursor = max(cursor, open_time + interval_ms)
        if cursor > end_ms:
            break

    if cursor <= end_ms:
        missing.append((cursor, end_ms))

    return missing


def insert_orderbook_snapshot(
    symbol: str,
    snapshot: dict,
    *,
    db_path: str | Path | None = None,
    source: str = "revolut",
) -> None:
    ensure_schema(db_path, include_orderbook_snapshots=True)

    bids = list(snapshot.get("bids", []))[:5]
    asks = list(snapshot.get("asks", []))[:5]

    def _px_sz(levels: list[tuple[float, float]], idx: int) -> tuple[float | None, float | None]:
        if idx >= len(levels):
            return None, None
        price, size = levels[idx]
        return float(price), float(size)

    bid_vals = []
    ask_vals = []
    for i in range(5):
        bid_vals.extend(_px_sz(bids, i))
        ask_vals.extend(_px_sz(asks, i))

    with connect(db_path) as conn:
        conn.execute(
            """
            INSERT INTO orderbook_snapshots (
                symbol, ts, best_bid, best_ask, spread,
                bid_1_price, bid_1_size, bid_2_price, bid_2_size, bid_3_price, bid_3_size,
                bid_4_price, bid_4_size, bid_5_price, bid_5_size,
                ask_1_price, ask_1_size, ask_2_price, ask_2_size, ask_3_price, ask_3_size,
                ask_4_price, ask_4_size, ask_5_price, ask_5_size, source
            ) VALUES (
                ?, ?, ?, ?, ?,
                ?, ?, ?, ?, ?, ?,
                ?, ?, ?, ?,
                ?, ?, ?, ?, ?, ?,
                ?, ?, ?, ?, ?
            )
            """,
            (
                symbol,
                int(snapshot["ts"]),
                snapshot.get("best_bid"),
                snapshot.get("best_ask"),
                snapshot.get("spread"),
                *bid_vals,
                *ask_vals,
                source,
            ),
        )
