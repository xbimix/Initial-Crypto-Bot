from __future__ import annotations

from data import live_sync_scheduler


def setup_function():
    live_sync_scheduler._last_sync_at.clear()


def test_incremental_sync_scheduler_caps_requests(monkeypatch):
    calls: list[tuple[str, str]] = []

    def fake_sync_new_candles(*, symbol, timeframe, include_partial, cfg=None):
        calls.append((symbol, timeframe))
        return {"requests": 1, "fetched": 10, "inserted": 5}

    monkeypatch.setattr(live_sync_scheduler, "sync_new_candles", fake_sync_new_candles)

    cfg = {
        "market_data": {
            "incremental_sync_enabled": True,
            "sync_timeframes": ["1m", "5m", "15m"],
            "sync_cadence_seconds": {"1m": 0, "5m": 0, "15m": 0},
            "max_sync_requests_per_tick": 2,
        }
    }
    summary = live_sync_scheduler.run_incremental_sync_tick(
        cfg=cfg,
        symbols=["BTC-USD", "ETH-USD"],
        now_epoch=10_000.0,
    )

    assert summary["enabled"] is True
    assert summary["requests"] == 2
    assert len(calls) == 2
    assert summary["errors"] == 0


def test_incremental_sync_scheduler_respects_disable():
    cfg = {"market_data": {"incremental_sync_enabled": False}}
    summary = live_sync_scheduler.run_incremental_sync_tick(
        cfg=cfg,
        symbols=["BTC-USD"],
        now_epoch=10_000.0,
    )
    assert summary["enabled"] is False
    assert summary["requests"] == 0


def test_incremental_sync_scheduler_caps_attempts_on_errors(monkeypatch):
    calls: list[tuple[str, str]] = []

    def fake_sync_new_candles(*, symbol, timeframe, include_partial, cfg=None):
        calls.append((symbol, timeframe))
        raise RuntimeError("sync failed")

    monkeypatch.setattr(live_sync_scheduler, "sync_new_candles", fake_sync_new_candles)

    cfg = {
        "market_data": {
            "incremental_sync_enabled": True,
            "sync_timeframes": ["1m", "5m", "15m"],
            "sync_cadence_seconds": {"1m": 0, "5m": 0, "15m": 0},
            "max_sync_requests_per_tick": 2,
        }
    }

    summary = live_sync_scheduler.run_incremental_sync_tick(
        cfg=cfg,
        symbols=["BTC-USD", "ETH-USD", "SOL-USD"],
        now_epoch=20_000.0,
    )

    assert summary["enabled"] is True
    assert summary["attempted_jobs"] == 2
    assert summary["requests"] == 0
    assert summary["errors"] == 2
    assert len(calls) == 2


def test_incremental_sync_scheduler_retries_errors_with_backoff(monkeypatch):
    calls: list[tuple[str, str]] = []

    def fake_sync_new_candles(*, symbol, timeframe, include_partial, cfg=None):
        calls.append((symbol, timeframe))
        raise RuntimeError("transient failure")

    monkeypatch.setattr(live_sync_scheduler, "sync_new_candles", fake_sync_new_candles)

    cfg = {
        "market_data": {
            "incremental_sync_enabled": True,
            "sync_timeframes": ["1d"],
            "sync_cadence_seconds": {"1d": 2700},
            "sync_error_backoff_seconds": 30,
            "max_sync_requests_per_tick": 1,
        }
    }

    summary_a = live_sync_scheduler.run_incremental_sync_tick(
        cfg=cfg,
        symbols=["BTC-USD"],
        now_epoch=1_000.0,
    )
    assert summary_a["errors"] == 1
    assert len(calls) == 1

    summary_b = live_sync_scheduler.run_incremental_sync_tick(
        cfg=cfg,
        symbols=["BTC-USD"],
        now_epoch=1_020.0,
    )
    assert summary_b["attempted_jobs"] == 0
    assert len(calls) == 1

    summary_c = live_sync_scheduler.run_incremental_sync_tick(
        cfg=cfg,
        symbols=["BTC-USD"],
        now_epoch=1_031.0,
    )
    assert summary_c["errors"] == 1
    assert len(calls) == 2


def test_incremental_sync_scheduler_avoids_timeframe_starvation(monkeypatch):
    calls: list[tuple[str, str]] = []

    def fake_sync_new_candles(*, symbol, timeframe, include_partial, cfg=None):
        calls.append((symbol, timeframe))
        return {"requests": 1, "fetched": 1, "inserted": 1, "status": "ok"}

    monkeypatch.setattr(live_sync_scheduler, "sync_new_candles", fake_sync_new_candles)

    cfg = {
        "market_data": {
            "incremental_sync_enabled": True,
            "sync_timeframes": ["1m", "5m", "15m"],
            "sync_cadence_seconds": {"1m": 1, "5m": 1, "15m": 1},
            "max_sync_requests_per_tick": 2,
        }
    }

    for tick in range(6):
        live_sync_scheduler.run_incremental_sync_tick(
            cfg=cfg,
            symbols=["BTC-USD", "ETH-USD", "SOL-USD"],
            now_epoch=10_000.0 + tick,
        )

    seen_symbols = {symbol for symbol, _ in calls}
    seen_timeframes = {tf for _, tf in calls}
    assert len(calls) >= 6
    assert len(seen_symbols) >= 2
    assert len(seen_timeframes) >= 2


def test_incremental_sync_scheduler_prefers_core_timeframes_when_equally_due(monkeypatch):
    calls: list[tuple[str, str]] = []

    def fake_sync_new_candles(*, symbol, timeframe, include_partial, cfg=None):
        calls.append((symbol, timeframe))
        return {"requests": 1, "fetched": 1, "inserted": 1, "status": "ok"}

    monkeypatch.setattr(live_sync_scheduler, "sync_new_candles", fake_sync_new_candles)

    cfg = {
        "market_data": {
            "incremental_sync_enabled": True,
            "sync_timeframes": ["1m", "1h", "4h"],
            "sync_cadence_seconds": {"1m": 1, "1h": 1, "4h": 1},
            "max_sync_requests_per_tick": 1,
        }
    }
    live_sync_scheduler.run_incremental_sync_tick(
        cfg=cfg,
        symbols=["BTC-USD"],
        now_epoch=50_000.0,
    )
    assert calls
    assert calls[0][1] in {"1h", "4h"}


def test_incremental_sync_scheduler_aggregates_extended_insert_metrics(monkeypatch):
    def fake_sync_new_candles(*, symbol, timeframe, include_partial, cfg=None):
        return {
            "requests": 1,
            "fetched": 10,
            "inserted": 8,
            "new_inserted": 3,
            "updated_existing": 5,
            "candidate_new": 8,
            "eligible_closed": 7,
            "skipped_existing": 2,
            "skipped_partial": 1,
            "status": "ok",
        }

    monkeypatch.setattr(live_sync_scheduler, "sync_new_candles", fake_sync_new_candles)
    cfg = {
        "market_data": {
            "incremental_sync_enabled": True,
            "sync_timeframes": ["1h"],
            "sync_cadence_seconds": {"1h": 0},
            "max_sync_requests_per_tick": 2,
        }
    }
    summary = live_sync_scheduler.run_incremental_sync_tick(
        cfg=cfg,
        symbols=["BTC-USD", "ETH-USD"],
        now_epoch=77_000.0,
    )

    assert summary["requests"] == 2
    assert summary["inserted"] == 16
    assert summary["new_inserted"] == 6
    assert summary["updated_existing"] == 10
    assert summary["candidate_new"] == 16
    assert summary["eligible_closed"] == 14
    assert summary["skipped_existing"] == 4
    assert summary["skipped_partial"] == 2
