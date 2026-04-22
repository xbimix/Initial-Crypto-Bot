from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from data import market_data_service
from data import revolut_backfill
from data import revolut_candle_fetcher
from data import revolut_incremental_sync
from data import revolut_market_db
from data import revolut_orderbook_cache


def _db_path(tmp_path: Path) -> Path:
    return tmp_path / "market_data.db"


def setup_function():
    revolut_candle_fetcher._WORKING_CANDLE_REQUEST = None
    revolut_candle_fetcher._CANDLE_SCOPE_UNAUTHORIZED_UNTIL_EPOCH = 0.0
    revolut_candle_fetcher._ENDPOINT_CAPABILITY_CACHE = {}


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


def test_candle_upsert_infers_close_time_when_missing(tmp_path: Path):
    db_path = _db_path(tmp_path)
    symbol = "BTC-USD"
    timeframe = "1m"
    revolut_market_db.upsert_candles(
        symbol,
        timeframe,
        [{"ts": 60_000, "open": 1.0, "high": 1.1, "low": 0.9, "close": 1.0, "volume": 1.0}],
        db_path=db_path,
    )
    rows = revolut_market_db.get_candles(symbol, timeframe, db_path=db_path, ascending=True)
    assert len(rows) == 1
    assert rows[0]["close_time"] == 119_999


def test_backfill_null_close_times_updates_existing_rows(tmp_path: Path):
    db_path = _db_path(tmp_path)
    symbol = "BTC-USD"
    timeframe = "1m"
    revolut_market_db.ensure_schema(db_path)
    with revolut_market_db.connect(db_path) as conn:
        conn.execute(
            """
            INSERT INTO candles (
                symbol, timeframe, open_time, close_time, open, high, low, close, volume, source, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (symbol, timeframe, 120_000, None, 1.0, 1.1, 0.9, 1.0, 1.0, "test", 1),
        )
        conn.commit()
    pre = revolut_market_db.audit_close_time_integrity(db_path=db_path)
    assert pre["null_close_time_count"] == 1
    result = revolut_market_db.backfill_null_close_times(db_path=db_path, dry_run=False)
    assert result["updated_rows"] == 1
    rows = revolut_market_db.get_candles(symbol, timeframe, db_path=db_path, ascending=True)
    assert rows[0]["close_time"] == 179_999
    post = revolut_market_db.audit_close_time_integrity(db_path=db_path)
    assert post["null_close_time_count"] == 0


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


def test_normalize_revolut_candles_supports_start_field_schema():
    payload = {
        "data": [
            {"start": 3_000, "open": "12", "high": "13", "low": "11", "close": "12.5", "volume": "7"},
        ]
    }
    normalized = revolut_candle_fetcher.normalize_revolut_candles(payload)
    assert len(normalized) == 1
    assert normalized[0]["ts"] == 3_000
    assert normalized[0]["open"] == 12.0
    assert normalized[0]["close"] == 12.5


def test_fetch_candles_tries_symbol_path_variant(monkeypatch):
    calls: list[tuple[str, bool, dict | None]] = []

    def fake_get(path, params=None, auth=False):
        calls.append((path, auth, params))
        if "/market-data/candles/BTC-USD" in path:
            return {
                "data": [
                    {"start": 1_000, "open": "1", "high": "2", "low": "0.5", "close": "1.5", "volume": "3"}
                ]
            }
        raise RuntimeError("not found")

    monkeypatch.setattr(revolut_candle_fetcher, "_get", fake_get)
    rows = revolut_candle_fetcher.fetch_candles(
        symbol="BTC-USD",
        interval_minutes=60,
        since_ms=1_000,
        until_ms=60_000,
    )
    assert rows
    assert rows[0]["ts"] == 1_000
    assert any("/market-data/candles/BTC-USD" in path for path, _auth, _params in calls)


def test_fetch_candles_prefers_openapi_canonical_symbol_endpoint(monkeypatch):
    calls: list[tuple[str, bool, dict | None]] = []
    monkeypatch.setattr(revolut_candle_fetcher, "_WORKING_CANDLE_REQUEST", None)

    def fake_get(path, params=None, auth=False):
        calls.append((path, auth, params))
        if path == "/candles/BTC-USD":
            return {
                "data": [
                    {
                        "start": 1_000,
                        "open": "1",
                        "high": "2",
                        "low": "0.5",
                        "close": "1.5",
                        "volume": "3",
                    }
                ]
            }
        raise RuntimeError("not found")

    monkeypatch.setattr(revolut_candle_fetcher, "_get", fake_get)
    rows = revolut_candle_fetcher.fetch_candles(
        symbol="BTC-USD",
        interval_minutes=60,
        since_ms=1_000,
        until_ms=60_000,
    )
    assert rows
    assert calls
    first_path, first_auth, first_params = calls[0]
    assert first_path == "/candles/BTC-USD"
    assert first_auth is True
    assert isinstance(first_params, dict)
    assert {"interval", "since", "until"}.issubset(set(first_params.keys()))
    assert "symbol" not in first_params


def test_fetch_candles_normalizes_slash_symbol_to_canonical_path(monkeypatch):
    calls: list[tuple[str, bool, dict | None]] = []
    monkeypatch.setattr(revolut_candle_fetcher, "_WORKING_CANDLE_REQUEST", None)

    def fake_get(path, params=None, auth=False):
        calls.append((path, auth, params))
        if path == "/candles/BTC-USD":
            return {
                "data": [
                    {
                        "start": 1_000,
                        "open": "1",
                        "high": "2",
                        "low": "0.5",
                        "close": "1.5",
                        "volume": "3",
                    }
                ]
            }
        raise RuntimeError("not found")

    monkeypatch.setattr(revolut_candle_fetcher, "_get", fake_get)
    rows = revolut_candle_fetcher.fetch_candles(
        symbol="btc/usd",
        interval_minutes=60,
        since_ms=1_000,
        until_ms=60_000,
    )
    assert rows
    assert calls
    first_path, _first_auth, first_params = calls[0]
    assert first_path == "/candles/BTC-USD"
    assert isinstance(first_params, dict)
    assert {"interval", "since", "until"}.issubset(set(first_params.keys()))
    assert "symbol" not in first_params


def test_fetch_candles_skips_public_candidates_by_default(monkeypatch):
    calls: list[str] = []

    def fake_get(path, params=None, auth=False):
        calls.append(path)
        raise RuntimeError("missing")

    monkeypatch.delenv("REVBOT_CANDLE_ALLOW_PUBLIC_FALLBACK", raising=False)
    monkeypatch.setattr(revolut_candle_fetcher, "_WORKING_CANDLE_REQUEST", None)
    monkeypatch.setattr(revolut_candle_fetcher, "_get", fake_get)
    try:
        revolut_candle_fetcher.fetch_candles(
            symbol="BTC-USD",
            interval_minutes=60,
            since_ms=1_000,
            until_ms=60_000,
        )
    except revolut_candle_fetcher.RevolutCandleFetchError:
        pass
    assert calls
    assert all(not path.startswith("/public/") for path in calls)


def test_fetch_candles_does_not_fall_back_to_public_on_auth_401_by_default(monkeypatch):
    calls: list[tuple[str, bool]] = []

    class _Resp:
        status_code = 401

    class _AuthErr(RuntimeError):
        def __init__(self):
            super().__init__("401 Client Error: Unauthorized")
            self.response = _Resp()

    def fake_get(path, params=None, auth=False):
        calls.append((path, auth))
        if auth:
            raise _AuthErr()
        if path.startswith("/public/"):
            return {"data": [{"start": 1_000, "open": "1", "high": "2", "low": "0.5", "close": "1.5", "volume": "3"}]}
        raise RuntimeError("unexpected path")

    monkeypatch.delenv("REVBOT_CANDLE_ALLOW_PUBLIC_FALLBACK", raising=False)
    monkeypatch.setattr(revolut_candle_fetcher, "_WORKING_CANDLE_REQUEST", None)
    monkeypatch.setattr(revolut_candle_fetcher, "_get", fake_get)

    with pytest.raises(revolut_candle_fetcher.RevolutCandleFetchError):
        revolut_candle_fetcher.fetch_candles(
            symbol="BTC-USD",
            interval_minutes=60,
            since_ms=1_000,
            until_ms=60_000,
        )
    assert any(auth for _path, auth in calls)
    assert all(not path.startswith("/public/") for path, _auth in calls)


def test_fetch_candles_falls_back_to_public_on_auth_401_when_enabled(monkeypatch):
    calls: list[tuple[str, bool]] = []

    class _Resp:
        status_code = 401

    class _AuthErr(RuntimeError):
        def __init__(self):
            super().__init__("401 Client Error: Unauthorized")
            self.response = _Resp()

    def fake_get(path, params=None, auth=False):
        calls.append((path, auth))
        if auth:
            raise _AuthErr()
        if path.startswith("/public/"):
            return {"data": [{"start": 1_000, "open": "1", "high": "2", "low": "0.5", "close": "1.5", "volume": "3"}]}
        raise RuntimeError("unexpected path")

    monkeypatch.delenv("REVBOT_CANDLE_ALLOW_PUBLIC_FALLBACK", raising=False)
    monkeypatch.setattr(revolut_candle_fetcher, "_WORKING_CANDLE_REQUEST", None)
    monkeypatch.setattr(revolut_candle_fetcher, "_get", fake_get)

    rows = revolut_candle_fetcher.fetch_candles(
        symbol="BTC-USD",
        interval_minutes=60,
        since_ms=1_000,
        until_ms=60_000,
        allow_public_fallback=True,
    )
    assert rows
    assert any(auth for _path, auth in calls)
    assert any((not auth) and path.startswith("/public/") for path, auth in calls)


def test_fetch_candles_records_endpoint_telemetry(monkeypatch):
    monkeypatch.setattr(revolut_candle_fetcher, "_WORKING_CANDLE_REQUEST", None)
    monkeypatch.setattr(revolut_candle_fetcher, "_ENDPOINT_CAPABILITY_CACHE", {})
    monkeypatch.setattr(
        revolut_candle_fetcher,
        "_CANDLE_TELEMETRY",
        {
            "fetch_calls": 0,
            "success_calls": 0,
            "failed_calls": 0,
            "official_success_calls": 0,
            "public_success_calls": 0,
            "candidate_success": {},
            "candidate_failures": {},
        },
    )

    def fake_get(path, params=None, auth=False):
        if auth:
            return {
                "data": [
                    {"start": 1_000, "open": "1", "high": "2", "low": "0.5", "close": "1.5", "volume": "3"}
                ]
            }
        raise RuntimeError("unexpected public call")

    monkeypatch.setattr(revolut_candle_fetcher, "_get", fake_get)
    rows = revolut_candle_fetcher.fetch_candles(
        symbol="BTC-USD",
        interval_minutes=60,
        since_ms=1_000,
        until_ms=60_000,
    )
    assert rows
    telemetry = revolut_candle_fetcher.get_candle_fetch_telemetry()
    assert telemetry["fetch_calls"] >= 1
    assert telemetry["success_calls"] >= 1
    assert telemetry["official_success_calls"] >= 1
    assert telemetry["failed_calls"] == 0


def test_fetch_candles_skips_blocked_capability_candidate(monkeypatch):
    key_primary = "auth:/candles/BTC-USD:symbolless_primary"
    key_seconds = "auth:/candles/BTC-USD:symbolless_seconds"
    monkeypatch.setattr(
        revolut_candle_fetcher,
        "_ENDPOINT_CAPABILITY_CACHE",
        {
            key_primary: {
                "status": "auth_unauthorized",
                "updated_epoch": revolut_candle_fetcher.time.time(),
                "success_count": 0,
                "failure_count": 1,
                "last_status_code": 401,
            },
            key_seconds: {
                "status": "auth_unauthorized",
                "updated_epoch": revolut_candle_fetcher.time.time(),
                "success_count": 0,
                "failure_count": 1,
                "last_status_code": 401,
            }
        },
    )
    monkeypatch.setattr(revolut_candle_fetcher, "_WORKING_CANDLE_REQUEST", None)
    calls: list[tuple[str, bool]] = []

    def fake_get(path, params=None, auth=False):
        calls.append((path, auth))
        if auth and path.startswith("/market-data/candles/"):
            return {
                "data": [
                    {"start": 1_000, "open": "1", "high": "2", "low": "0.5", "close": "1.5", "volume": "3"}
                ]
            }
        raise RuntimeError("not found")

    monkeypatch.setattr(revolut_candle_fetcher, "_get", fake_get)
    rows = revolut_candle_fetcher.fetch_candles(
        symbol="BTC-USD",
        interval_minutes=60,
        since_ms=1_000,
        until_ms=60_000,
    )
    assert rows
    assert all(path != "/candles/BTC-USD" for path, _auth in calls)


def test_fetch_candles_does_not_reuse_symbol_bound_cached_candidate_across_symbols(monkeypatch):
    monkeypatch.setattr(
        revolut_candle_fetcher,
        "_WORKING_CANDLE_REQUEST",
        {"path": "/candles/BTC-USD", "mode": "symbolless_primary", "auth": True, "symbol": "BTC-USD"},
    )
    calls: list[str] = []

    def fake_get(path, params=None, auth=False):
        calls.append(path)
        if path == "/candles/AAVE-USD":
            return {
                "data": [
                    {"start": 1_000, "open": "100", "high": "101", "low": "99", "close": "100.5", "volume": "3"}
                ]
            }
        raise RuntimeError("not found")

    monkeypatch.setattr(revolut_candle_fetcher, "_get", fake_get)
    rows = revolut_candle_fetcher.fetch_candles(
        symbol="AAVE-USD",
        interval_minutes=60,
        since_ms=1_000,
        until_ms=60_000,
    )
    assert rows
    assert "/candles/BTC-USD" not in calls
    assert "/candles/AAVE-USD" in calls


def test_fetch_candles_honors_auth_scope_cooldown(monkeypatch):
    monkeypatch.setattr(
        revolut_candle_fetcher,
        "_CANDLE_SCOPE_UNAUTHORIZED_UNTIL_EPOCH",
        revolut_candle_fetcher.time.time() + 120.0,
    )
    with pytest.raises(revolut_candle_fetcher.RevolutCandleFetchError) as exc:
        revolut_candle_fetcher.fetch_candles(
            symbol="BTC-USD",
            interval_minutes=60,
            since_ms=1_000,
            until_ms=60_000,
        )
    assert getattr(exc.value, "permanent", False) is True
    assert "cooldown active" in str(exc.value).lower()


def test_fetch_candles_uses_public_when_auth_cooldown_and_public_enabled(monkeypatch):
    calls: list[tuple[str, bool]] = []
    monkeypatch.setattr(
        revolut_candle_fetcher,
        "_CANDLE_SCOPE_UNAUTHORIZED_UNTIL_EPOCH",
        revolut_candle_fetcher.time.time() + 120.0,
    )

    def fake_get(path, params=None, auth=False):
        calls.append((path, auth))
        if not auth and path.startswith("/public/"):
            return {
                "data": [
                    {"start": 1_000, "open": "1", "high": "2", "low": "0.5", "close": "1.5", "volume": "3"}
                ]
            }
        raise RuntimeError("unexpected path")

    monkeypatch.setattr(revolut_candle_fetcher, "_get", fake_get)
    rows = revolut_candle_fetcher.fetch_candles(
        symbol="BTC-USD",
        interval_minutes=60,
        since_ms=1_000,
        until_ms=60_000,
        allow_public_fallback=True,
    )
    assert rows
    assert calls
    assert all(not auth for _path, auth in calls)
    assert all(path.startswith("/public/") for path, _auth in calls)


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
    assert result["new_inserted"] == 1
    assert result["updated_existing"] == 0
    assert result["candidate_new"] == 2
    assert result["eligible_closed"] == 1
    assert result["skipped_existing"] == 0
    assert result["skipped_partial"] == 1
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


def test_incremental_sync_bootstraps_configured_lookback_when_history_missing(tmp_path: Path, monkeypatch):
    db_path = _db_path(tmp_path)
    symbol = "BTC-USD"
    timeframe = "1h"
    now_ms = 20_000_000_000
    lookback_ms = 180 * 24 * 60 * 60 * 1000
    calls: list[tuple[int, int]] = []

    def fake_fetch(symbol, interval_minutes, since_ms, until_ms):
        calls.append((since_ms, until_ms))
        return []

    monkeypatch.setattr(revolut_incremental_sync, "fetch_candles", fake_fetch)

    result = revolut_incremental_sync.sync_new_candles(
        symbol=symbol,
        timeframe=timeframe,
        db_path=db_path,
        now_ms=now_ms,
    )

    assert result["requests"] >= 1
    assert calls
    assert calls[0][0] == now_ms - lookback_ms
    assert calls[-1][1] == now_ms


def test_incremental_sync_marks_unsupported_when_official_candles_unavailable_without_fallback(tmp_path: Path, monkeypatch):
    db_path = _db_path(tmp_path)
    symbol = "BTC-USD"
    timeframe = "1m"
    now_ms = 180_000

    def fake_fetch(symbol, interval_minutes, since_ms, until_ms):
        raise revolut_incremental_sync.RevolutCandleFetchError(
            "No supported Revolut candle endpoint available for this runtime/auth scope",
            permanent=True,
        )

    monkeypatch.delenv("REVBOT_ALLOW_SNAPSHOT_CANDLE_FALLBACK", raising=False)
    monkeypatch.setattr(revolut_incremental_sync, "fetch_candles", fake_fetch)

    result = revolut_incremental_sync.sync_new_candles(
        symbol=symbol,
        timeframe=timeframe,
        db_path=db_path,
        now_ms=now_ms,
    )
    assert result["status"] == "unsupported"
    assert result["source"] == "revolut"
    assert result["inserted"] == 0


def test_incremental_sync_passes_public_fallback_policy_from_source_map(tmp_path: Path, monkeypatch):
    db_path = _db_path(tmp_path)
    calls: list[bool] = []

    def fake_fetch(symbol, interval_minutes, since_ms, until_ms, allow_public_fallback=None):
        calls.append(bool(allow_public_fallback))
        return []

    monkeypatch.setattr(revolut_incremental_sync, "fetch_candles", fake_fetch)

    cfg = {
        "market_data": {
            "source_map": {
                "candles": {
                    "allow_public_fallback": True,
                }
            }
        }
    }
    revolut_incremental_sync.sync_new_candles(
        symbol="BTC-USD",
        timeframe="1m",
        db_path=db_path,
        now_ms=180_000,
        cfg=cfg,
    )
    assert calls
    assert all(calls)


def test_incremental_sync_uses_snapshot_fallback_from_source_map(tmp_path: Path, monkeypatch):
    db_path = _db_path(tmp_path)
    symbol = "BTC-USD"
    timeframe = "1m"
    now_ms = 180_000
    revolut_market_db.upsert_candles(
        symbol=symbol,
        timeframe=timeframe,
        db_path=db_path,
        candles=[
            {"ts": 60_000, "open": 1.0, "high": 1.1, "low": 0.9, "close": 1.0, "volume": 1.0, "close_time": 119_999}
        ],
    )

    def fake_fetch(symbol, interval_minutes, since_ms, until_ms, allow_public_fallback=None):
        raise revolut_incremental_sync.RevolutCandleFetchError("unavailable", permanent=True)

    monkeypatch.setattr(revolut_incremental_sync, "fetch_candles", fake_fetch)
    monkeypatch.setattr(
        revolut_incremental_sync,
        "_derive_candles_from_price_history",
        lambda **kwargs: [
            {
                "ts": 120_000,
                "open": 1.0,
                "high": 1.1,
                "low": 0.9,
                "close": 1.05,
                "volume": 0.0,
                "close_time": 179_999,
            }
        ],
    )

    cfg = {
        "market_data": {
            "source_map": {
                "candles": {
                    "allow_snapshot_fallback": True,
                }
            }
        }
    }
    result = revolut_incremental_sync.sync_new_candles(
        symbol=symbol,
        timeframe=timeframe,
        db_path=db_path,
        now_ms=now_ms,
        cfg=cfg,
    )
    assert result["status"] == "degraded"
    assert result["source"] == "snapshot_derived"
    assert result["inserted"] == 1


def test_incremental_sync_uses_snapshot_fallback_on_retryable_error_when_enabled(tmp_path: Path, monkeypatch):
    db_path = _db_path(tmp_path)
    symbol = "BTC-USD"
    timeframe = "1m"
    now_ms = 180_000

    def fake_fetch(symbol, interval_minutes, since_ms, until_ms, allow_public_fallback=None):
        raise revolut_incremental_sync.RevolutCandleFetchError("temporary upstream issue", permanent=False)

    monkeypatch.setattr(revolut_incremental_sync, "fetch_candles", fake_fetch)
    monkeypatch.setattr(
        revolut_incremental_sync,
        "_derive_candles_from_price_history",
        lambda **kwargs: [
            {
                "ts": 120_000,
                "open": 1.0,
                "high": 1.1,
                "low": 0.9,
                "close": 1.05,
                "volume": 0.0,
                "close_time": 179_999,
            }
        ],
    )
    cfg = {
        "market_data": {
            "source_map": {
                "candles": {
                    "allow_snapshot_fallback": True,
                }
            }
        }
    }

    result = revolut_incremental_sync.sync_new_candles(
        symbol=symbol,
        timeframe=timeframe,
        db_path=db_path,
        now_ms=now_ms,
        cfg=cfg,
    )
    assert result["status"] == "degraded"
    assert result["source"] == "snapshot_derived"
    assert result["inserted"] == 1
    assert str(result["note"]).startswith("official_candles_retryable_error:")


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


def test_orderbook_cache_reports_lru_eviction_and_stale_metrics(monkeypatch):
    revolut_orderbook_cache.orderbook_cache.clear()
    revolut_orderbook_cache._last_snapshot_persist_ts.clear()
    revolut_orderbook_cache._metrics.clear()
    revolut_orderbook_cache._metrics.update(
        {
            "hits": 0,
            "misses": 0,
            "stale_hits": 0,
            "evictions": 0,
            "updates": 0,
        }
    )
    monkeypatch.setattr(revolut_orderbook_cache, "ORDERBOOK_CACHE_MAX_SYMBOLS", 2)
    monkeypatch.setattr(revolut_orderbook_cache, "ORDERBOOK_CACHE_STALE_SECONDS", 10)

    now = {"epoch": 1_000.0}
    monkeypatch.setattr(revolut_orderbook_cache.time, "time", lambda: now["epoch"])

    def _fetch(symbol):
        base = {"BTC-USD": 100.0, "ETH-USD": 200.0, "SOL-USD": 300.0}[symbol]
        return {
            "ts": int(now["epoch"] * 1000),
            "bids": [(base - 1.0, 2.0)],
            "asks": [(base + 1.0, 2.0)],
            "best_bid": base - 1.0,
            "best_ask": base + 1.0,
            "spread": 2.0,
            "bid_volume_top5": 2.0,
            "ask_volume_top5": 2.0,
            "imbalance": 0.0,
            "source": "revolut",
        }

    monkeypatch.setattr(revolut_orderbook_cache, "fetch_orderbook_top5", _fetch)
    revolut_orderbook_cache.update_orderbook_cache("BTC-USD")
    revolut_orderbook_cache.update_orderbook_cache("ETH-USD")
    revolut_orderbook_cache.update_orderbook_cache("SOL-USD")
    # BTC should be evicted due to max-size=2.
    assert revolut_orderbook_cache.get_orderbook_cache("BTC-USD") is None

    now["epoch"] = 1_015.0
    cached = revolut_orderbook_cache.get_orderbook_cache("ETH-USD", stale_after_seconds=10)
    assert cached is not None
    assert cached["stale"] is True

    metrics = revolut_orderbook_cache.get_orderbook_cache_metrics()
    assert metrics["size"] == 2
    assert metrics["evictions"] >= 1
    assert metrics["misses"] >= 1
    assert metrics["hits"] >= 1
    assert metrics["stale_hits"] >= 1


def test_market_data_service_unsupported_timeframe_meta(tmp_path: Path):
    db_path = _db_path(tmp_path)
    service = market_data_service.MarketDataService(db_path=db_path)
    meta = service.get_candle_meta("BTC-USD", "2m")
    assert meta["supported"] is False
    assert meta["supported_timeframe"] is False


def test_market_data_service_meta_handles_transient_db_errors_without_unsupported(tmp_path: Path, monkeypatch):
    db_path = _db_path(tmp_path)
    service = market_data_service.MarketDataService(db_path=db_path)

    def _locked(*args, **kwargs):
        raise sqlite3.OperationalError("database is locked")

    monkeypatch.setattr(service.store, "get_latest_open_time", _locked)
    meta = service.get_candle_meta("BTC-USD", "1h")
    assert meta["supported"] is True
    assert meta["supported_timeframe"] is True
    assert meta["reason"] == "meta_fetch_failed"


def test_market_data_service_module_meta_forwards_stale_after_seconds(monkeypatch):
    captured: dict[str, object] = {}

    class _FakeService:
        def get_candle_meta(self, symbol: str, timeframe: str, *, stale_after_seconds: int | None = None):
            captured["symbol"] = symbol
            captured["timeframe"] = timeframe
            captured["stale_after_seconds"] = stale_after_seconds
            return {"supported": True, "reason": "ok"}

    monkeypatch.setattr(market_data_service, "_default_service", _FakeService())

    meta = market_data_service.get_candle_meta("BTC-USD", "1h", stale_after_seconds=7_200)
    assert meta["supported"] is True
    assert captured == {
        "symbol": "BTC-USD",
        "timeframe": "1h",
        "stale_after_seconds": 7_200,
    }


def test_market_data_service_meta_uses_adaptive_staleness_when_not_provided(tmp_path: Path, monkeypatch):
    db_path = _db_path(tmp_path)
    symbol = "BTC-USD"
    timeframe = "1h"
    now_ms = 10_000_000_000
    revolut_market_db.upsert_candles(
        symbol=symbol,
        timeframe=timeframe,
        candles=[
            {
                "ts": now_ms - (2 * 3_600_000),
                "open": 1.0,
                "high": 1.1,
                "low": 0.9,
                "close": 1.0,
                "volume": 1.0,
                "close_time": now_ms - (1 * 3_600_000),
            }
        ],
        db_path=db_path,
    )
    service = market_data_service.MarketDataService(db_path=db_path)
    monkeypatch.setattr(market_data_service.time, "time", lambda: now_ms / 1000.0)
    monkeypatch.setattr(
        service.store,
        "get_last_updated_at",
        lambda *_args, **_kwargs: now_ms - (2 * 3_600_000),
    )

    adaptive_meta = service.get_candle_meta(symbol, timeframe)
    strict_meta = service.get_candle_meta(symbol, timeframe, stale_after_seconds=120)

    assert adaptive_meta["supported"] is True
    assert adaptive_meta["stale"] is False
    assert strict_meta["stale"] is True


def test_market_data_service_meta_prefers_candle_time_over_write_time(tmp_path: Path, monkeypatch):
    db_path = _db_path(tmp_path)
    symbol = "BTC-USD"
    timeframe = "1m"
    now_ms = 20_000_000_000
    old_open = now_ms - (10 * 60_000)
    revolut_market_db.upsert_candles(
        symbol=symbol,
        timeframe=timeframe,
        candles=[
            {
                "ts": old_open,
                "open": 100.0,
                "high": 101.0,
                "low": 99.0,
                "close": 100.5,
                "volume": 3.0,
                "close_time": old_open + 59_999,
            }
        ],
        db_path=db_path,
    )
    service = market_data_service.MarketDataService(db_path=db_path)
    monkeypatch.setattr(market_data_service.time, "time", lambda: now_ms / 1000.0)
    # Simulate a fresh write timestamp even though market candle is old.
    monkeypatch.setattr(service.store, "get_last_updated_at", lambda *_args, **_kwargs: now_ms)

    meta = service.get_candle_meta(symbol, timeframe, stale_after_seconds=300)
    assert meta["freshness_reference"] == "latest_candle_close_estimate"
    assert meta["age_seconds"] is not None and float(meta["age_seconds"]) >= 540.0
    assert meta["stale"] is True


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
