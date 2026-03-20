from __future__ import annotations

import sqlite3
from pathlib import Path

from data import market_data_service
from data import revolut_backfill
from data import revolut_candle_fetcher
from data import revolut_incremental_sync
from data import revolut_market_db
from data import revolut_orderbook_cache


def _db_path(tmp_path: Path) -> Path:
    return tmp_path / "market_data.db"


def test_sqlite_schema_creation_and_indexes(tmp_path: Path):
    db_path = _db_path(tmp_path)
    revolut_market_db.ensure_schema(db_path)

    with sqlite3.connect(str(db_path)) as conn:
        tables = {
            row[0]
            for row in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            ).fetchall()
        }
        indexes = {
            row[0]
            for row in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='index'"
            ).fetchall()
        }

    assert "candles" in tables
    assert "orderbook_snapshots" in tables
    assert "sync_state" in tables
    assert "idx_candles_symbol_timeframe_open_time" in indexes
    assert "idx_candles_symbol_open_time" in indexes
    assert "idx_sync_state_updated_at" in indexes


def test_candle_upsert_and_deduplication(tmp_path: Path):
    db_path = _db_path(tmp_path)
    symbol = "BTC-USD"
    timeframe = "1m"
    seed_rows = [
        {"ts": 1_000, "open": 1.0, "high": 2.0, "low": 0.5, "close": 1.5, "volume": 10.0, "close_time": 1_059},
        {"ts": 2_000, "open": 2.0, "high": 2.2, "low": 1.8, "close": 2.1, "volume": 12.0, "close_time": 2_059},
    ]
    revolut_market_db.upsert_candles(symbol, timeframe, seed_rows, db_path=db_path)
    assert revolut_market_db.get_candle_count(symbol, timeframe, db_path=db_path) == 2

    duplicate_with_update = [
        {"ts": 2_000, "open": 2.0, "high": 2.4, "low": 1.7, "close": 2.3, "volume": 14.0, "close_time": 2_059},
    ]
    revolut_market_db.upsert_candles(symbol, timeframe, duplicate_with_update, db_path=db_path)
    assert revolut_market_db.get_candle_count(symbol, timeframe, db_path=db_path) == 2

    rows = revolut_market_db.get_candles(symbol, timeframe, db_path=db_path, ascending=True)
    assert rows[1]["high"] == 2.4
    assert rows[1]["close"] == 2.3


def test_normalize_revolut_candles():
    payload = {
        "data": [
            {"t": 1_000, "o": "10", "h": "11", "l": "9", "c": "10.5", "v": "4", "T": 1_059},
            {"t": 1_000, "o": "10", "h": "12", "l": "9", "c": "11.0", "v": "5", "T": 1_059},
            {"open_time": 2_000, "open": 11, "high": 12, "low": 10, "close": 11.5, "volume": 6, "close_time": 2_059},
        ]
    }
    normalized = revolut_candle_fetcher.normalize_revolut_candles(payload)
    assert len(normalized) == 2
    assert normalized[0]["ts"] == 1_000
    assert normalized[0]["close"] == 11.0
    assert normalized[1]["ts"] == 2_000
    assert normalized[1]["volume"] == 6.0


def test_backfill_paginates_and_remains_idempotent(tmp_path: Path, monkeypatch):
    db_path = _db_path(tmp_path)
    symbol = "BTC-USD"
    timeframe = "1m"

    calls: list[tuple[int, int]] = []

    def fake_fetch(symbol, interval_minutes, since_ms, until_ms):
        calls.append((since_ms, until_ms))
        interval_ms = interval_minutes * 60_000
        rows = []
        ts = since_ms
        while ts <= until_ms:
            rows.append(
                {
                    "ts": ts,
                    "open": 1.0,
                    "high": 1.1,
                    "low": 0.9,
                    "close": 1.0,
                    "volume": 1.0,
                    "close_time": ts + interval_ms - 1,
                }
            )
            ts += interval_ms
        return rows

    monkeypatch.setattr(revolut_backfill, "fetch_candles", fake_fetch)

    interval_ms = 60_000
    start_ms = 0
    end_ms = (2_400 * interval_ms) - 1
    result_first = revolut_backfill.backfill_symbol_timeframe(
        symbol=symbol,
        timeframe=timeframe,
        target_start_ms=start_ms,
        target_end_ms=end_ms,
        db_path=db_path,
    )
    count_first = revolut_market_db.get_candle_count(symbol, timeframe, db_path=db_path)
    assert result_first["requests"] == 3
    assert result_first["checkpoint_status"] == "ok"
    assert count_first == 2_400
    sync_row = revolut_market_db.get_sync_state(symbol, timeframe, db_path=db_path)
    assert sync_row is not None
    assert sync_row["status"] == "ok"
    assert sync_row["earliest_ms"] == 0

    calls.clear()
    result_second = revolut_backfill.backfill_symbol_timeframe(
        symbol=symbol,
        timeframe=timeframe,
        target_start_ms=start_ms,
        target_end_ms=end_ms,
        db_path=db_path,
    )
    count_second = revolut_market_db.get_candle_count(symbol, timeframe, db_path=db_path)
    assert result_second["requests"] == 0
    assert result_second["checkpoint_status"] == "ok"
    assert count_second == count_first
    assert calls == []


def test_sync_state_and_missing_ranges(tmp_path: Path):
    db_path = _db_path(tmp_path)
    symbol = "BTC-USD"
    timeframe = "1m"
    interval_ms = 60_000
    candles = [
        {
            "ts": 0,
            "open": 1.0,
            "high": 1.1,
            "low": 0.9,
            "close": 1.0,
            "volume": 1.0,
            "close_time": interval_ms - 1,
        },
        {
            "ts": interval_ms * 2,
            "open": 1.0,
            "high": 1.1,
            "low": 0.9,
            "close": 1.0,
            "volume": 1.0,
            "close_time": (interval_ms * 3) - 1,
        },
    ]
    revolut_market_db.upsert_candles(symbol, timeframe, candles, db_path=db_path)
    gaps = revolut_market_db.find_missing_ranges(
        symbol,
        timeframe,
        target_start_ms=0,
        target_end_ms=(interval_ms * 3) - 1,
        db_path=db_path,
    )
    assert gaps == [(interval_ms, interval_ms)]

    revolut_market_db.upsert_sync_state(
        symbol,
        timeframe,
        earliest_ms=0,
        latest_ms=interval_ms * 2,
        last_sync_ms=123_456,
        status="ok",
        note="unit_test",
        db_path=db_path,
    )
    sync_row = revolut_market_db.get_sync_state(symbol, timeframe, db_path=db_path)
    assert sync_row is not None
    assert sync_row["status"] == "ok"
    assert sync_row["note"] == "unit_test"
    assert sync_row["latest_ms"] == interval_ms * 2


def test_incremental_sync_only_new_and_closed_rows(tmp_path: Path, monkeypatch):
    db_path = _db_path(tmp_path)
    symbol = "BTC-USD"
    timeframe = "1m"

    revolut_market_db.upsert_candles(
        symbol=symbol,
        timeframe=timeframe,
        db_path=db_path,
        candles=[
            {"ts": 60_000, "open": 1.0, "high": 1.1, "low": 0.9, "close": 1.0, "volume": 1.0, "close_time": 119_999}
        ],
    )

    now_ms = 180_000

    def fake_fetch(symbol, interval_minutes, since_ms, until_ms):
        assert since_ms == 120_000
        assert until_ms == now_ms
        return [
            {
                "ts": 120_000,
                "open": 1.0,
                "high": 1.1,
                "low": 0.9,
                "close": 1.0,
                "volume": 1.0,
                "close_time": 179_999,
            },
            {
                "ts": 180_000,
                "open": 1.0,
                "high": 1.1,
                "low": 0.9,
                "close": 1.0,
                "volume": 1.0,
                "close_time": 239_999,
            },
        ]

    monkeypatch.setattr(revolut_incremental_sync, "fetch_candles", fake_fetch)
    result = revolut_incremental_sync.sync_new_candles(
        symbol=symbol,
        timeframe=timeframe,
        db_path=db_path,
        now_ms=now_ms,
    )
    rows = revolut_market_db.get_candles(symbol, timeframe, db_path=db_path, ascending=True)

    assert result["fetched"] == 2
    assert result["inserted"] == 1
    assert result["partial_count"] == 1
    assert result["requests"] == 1
    assert len(rows) == 2
    assert rows[-1]["open_time"] == 120_000


def test_incremental_sync_paginates_when_gap_exceeds_revolut_limit(tmp_path: Path, monkeypatch):
    db_path = _db_path(tmp_path)
    symbol = "BTC-USD"
    timeframe = "1m"
    interval_ms = 60_000
    now_ms = (2_600 * interval_ms) - 1
    calls: list[tuple[int, int]] = []
    revolut_market_db.upsert_candles(
        symbol=symbol,
        timeframe=timeframe,
        db_path=db_path,
        candles=[
            {
                "ts": 0,
                "open": 1.0,
                "high": 1.1,
                "low": 0.9,
                "close": 1.0,
                "volume": 1.0,
                "close_time": interval_ms - 1,
            }
        ],
    )

    def fake_fetch(symbol, interval_minutes, since_ms, until_ms):
        calls.append((since_ms, until_ms))
        rows = []
        ts = since_ms
        while ts <= until_ms:
            rows.append(
                {
                    "ts": ts,
                    "open": 1.0,
                    "high": 1.1,
                    "low": 0.9,
                    "close": 1.0,
                    "volume": 1.0,
                    "close_time": ts + interval_ms - 1,
                }
            )
            ts += interval_ms
        return rows

    monkeypatch.setattr(revolut_incremental_sync, "fetch_candles", fake_fetch)
    result = revolut_incremental_sync.sync_new_candles(
        symbol=symbol,
        timeframe=timeframe,
        db_path=db_path,
        now_ms=now_ms,
    )

    assert result["requests"] == 3
    assert len(calls) == 3
    assert result["inserted"] >= 2_550


def test_orderbook_top5_cache_and_optional_persistence(tmp_path: Path, monkeypatch):
    db_path = _db_path(tmp_path)
    symbol = "BTC-USD"

    def fake_get_order_book(symbol):
        return {
            "data": {
                "bids": [
                    {"p": "99.0", "q": "2"},
                    {"p": "98.5", "q": "3"},
                    {"p": "98.0", "q": "4"},
                    {"p": "97.5", "q": "5"},
                    {"p": "97.0", "q": "6"},
                    {"p": "96.5", "q": "7"},
                ],
                "asks": [
                    {"p": "100.0", "q": "1"},
                    {"p": "100.5", "q": "1.5"},
                    {"p": "101.0", "q": "2"},
                    {"p": "101.5", "q": "2.5"},
                    {"p": "102.0", "q": "3"},
                    {"p": "102.5", "q": "3.5"},
                ],
            }
        }

    monkeypatch.setattr(revolut_orderbook_cache, "get_order_book", fake_get_order_book)

    snapshot = revolut_orderbook_cache.update_orderbook_cache(
        symbol,
        persist=True,
        persist_every_seconds=30,
        db_path=db_path,
    )
    assert snapshot["best_bid"] == 99.0
    assert snapshot["best_ask"] == 100.0
    assert len(snapshot["bids"]) == 5
    assert len(snapshot["asks"]) == 5

    cached = revolut_orderbook_cache.get_orderbook_cache(symbol)
    assert cached is not None
    assert cached["spread"] == 1.0
    assert "imbalance" in cached

    first_ts = int(snapshot["ts"])
    monkeypatch.setattr(
        revolut_orderbook_cache,
        "fetch_orderbook_top5",
        lambda symbol: {
            **snapshot,
            "ts": first_ts + 10_000,
        },
    )
    revolut_orderbook_cache.update_orderbook_cache(
        symbol,
        persist=True,
        persist_every_seconds=30,
        db_path=db_path,
    )

    with sqlite3.connect(str(db_path)) as conn:
        persisted = conn.execute(
            "SELECT COUNT(*) FROM orderbook_snapshots WHERE symbol = ?",
            (symbol,),
        ).fetchone()[0]
    assert persisted == 1


def test_market_data_service_meta_and_latest_closed(tmp_path: Path):
    db_path = _db_path(tmp_path)
    symbol = "ETH-USD"
    timeframe = "1m"
    revolut_market_db.upsert_candles(
        symbol=symbol,
        timeframe=timeframe,
        db_path=db_path,
        candles=[
            {"ts": 1_000, "open": 1.0, "high": 1.1, "low": 0.9, "close": 1.0, "volume": 1.0, "close_time": 59_999},
            {"ts": 60_000, "open": 1.1, "high": 1.2, "low": 1.0, "close": 1.15, "volume": 2.0, "close_time": 119_999},
        ],
    )
    service = market_data_service.MarketDataService(db_path=db_path)

    meta = service.get_candle_meta(symbol, timeframe)
    latest_closed = service.get_latest_closed_candle(symbol, timeframe)

    assert meta["candle_count"] == 2
    assert meta["supported"] is True
    assert meta["supported_timeframe"] is True
    assert latest_closed is not None
    assert latest_closed["open_time"] == 60_000


def test_market_data_service_unsupported_timeframe_meta(tmp_path: Path):
    db_path = _db_path(tmp_path)
    service = market_data_service.MarketDataService(db_path=db_path)
    meta = service.get_candle_meta("BTC-USD", "2m")
    assert meta["supported"] is False
    assert meta["supported_timeframe"] is False


def test_candle_trim_to_lookback_limit(tmp_path: Path):
    db_path = _db_path(tmp_path)
    symbol = "BTC-USD"
    timeframe = "1m"
    rows = []
    for i in range(120):
        ts = i * 60_000
        rows.append(
            {
                "ts": ts,
                "open": 1.0,
                "high": 1.1,
                "low": 0.9,
                "close": 1.0,
                "volume": 1.0,
                "close_time": ts + 59_999,
            }
        )
    revolut_market_db.upsert_candles(symbol, timeframe, rows, db_path=db_path)
    trimmed = revolut_market_db.trim_candles_to_limit(symbol, timeframe, 50, db_path=db_path)
    remaining = revolut_market_db.get_candle_count(symbol, timeframe, db_path=db_path)
    assert trimmed > 0
    assert remaining == 50
