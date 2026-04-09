from __future__ import annotations

import sqlite3
from pathlib import Path

from data import revolut_market_db


def _write_db(path: Path, open_times: list[int]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(path) as conn:
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
        for open_time in open_times:
            conn.execute(
                """
                INSERT OR REPLACE INTO candles (
                    symbol, timeframe, open_time, close_time,
                    open, high, low, close, volume, source, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    "BTC-USD",
                    "1m",
                    int(open_time),
                    int(open_time + 60_000),
                    1.0,
                    1.0,
                    1.0,
                    1.0,
                    1.0,
                    "test",
                    int(open_time),
                ),
            )


def _max_open_time(path: Path) -> int | None:
    with sqlite3.connect(path) as conn:
        row = conn.execute("SELECT MAX(open_time) FROM candles").fetchone()
    value = row[0] if row else None
    return int(value) if value is not None else None


def test_resolve_db_path_seeds_runtime_db_when_missing(monkeypatch, tmp_path: Path):
    runtime_db = tmp_path / ".runtime" / "state" / "market_data.db"
    legacy_db = tmp_path / "crypto_bot" / "state" / "market_data.db"
    _write_db(legacy_db, [1000, 2000, 3000])

    monkeypatch.setattr(revolut_market_db, "DEFAULT_DB_PATH", runtime_db)
    monkeypatch.setattr(revolut_market_db, "LEGACY_DB_PATH", legacy_db)
    monkeypatch.setattr(revolut_market_db, "_DB_PATH_MIGRATION_CHECKED", set())

    resolved = revolut_market_db.resolve_db_path()
    assert resolved == runtime_db
    assert runtime_db.exists()
    assert _max_open_time(runtime_db) == 3000


def test_resolve_db_path_promotes_legacy_db_when_significantly_newer(monkeypatch, tmp_path: Path):
    runtime_db = tmp_path / ".runtime" / "state" / "market_data.db"
    legacy_db = tmp_path / "crypto_bot" / "state" / "market_data.db"
    _write_db(runtime_db, [1000, 2000, 3000])
    _write_db(legacy_db, [1000, 2000, 3000 + (7 * 60 * 60 * 1000)])

    monkeypatch.setattr(revolut_market_db, "DEFAULT_DB_PATH", runtime_db)
    monkeypatch.setattr(revolut_market_db, "LEGACY_DB_PATH", legacy_db)
    monkeypatch.setattr(revolut_market_db, "_DB_PATH_MIGRATION_CHECKED", set())

    revolut_market_db.resolve_db_path()
    assert _max_open_time(runtime_db) == _max_open_time(legacy_db)
    assert runtime_db.with_suffix(".db.pre_legacy_promote.bak").exists()


def test_resolve_db_path_keeps_runtime_db_when_newer(monkeypatch, tmp_path: Path):
    runtime_db = tmp_path / ".runtime" / "state" / "market_data.db"
    legacy_db = tmp_path / "crypto_bot" / "state" / "market_data.db"
    _write_db(runtime_db, [1000, 2000, 3000 + (10 * 60 * 60 * 1000)])
    _write_db(legacy_db, [1000, 2000, 3000])

    monkeypatch.setattr(revolut_market_db, "DEFAULT_DB_PATH", runtime_db)
    monkeypatch.setattr(revolut_market_db, "LEGACY_DB_PATH", legacy_db)
    monkeypatch.setattr(revolut_market_db, "_DB_PATH_MIGRATION_CHECKED", set())

    runtime_before = _max_open_time(runtime_db)
    revolut_market_db.resolve_db_path()
    assert _max_open_time(runtime_db) == runtime_before


def test_list_sync_states_filters_by_symbols_and_timeframes(tmp_path: Path):
    db = tmp_path / "market_data.db"
    revolut_market_db.upsert_sync_state(
        symbol="BTC-USD",
        timeframe="1m",
        earliest_ms=1,
        latest_ms=2,
        last_sync_ms=3,
        status="ok",
        note="",
        db_path=db,
    )
    revolut_market_db.upsert_sync_state(
        symbol="ETH-USD",
        timeframe="5m",
        earliest_ms=4,
        latest_ms=5,
        last_sync_ms=6,
        status="ok",
        note="",
        db_path=db,
    )
    rows = revolut_market_db.list_sync_states(
        symbols=["ETH-USD"],
        timeframes=["5m"],
        db_path=db,
    )
    assert len(rows) == 1
    assert rows[0]["symbol"] == "ETH-USD"
    assert rows[0]["timeframe"] == "5m"
