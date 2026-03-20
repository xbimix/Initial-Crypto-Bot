from __future__ import annotations

from data import live_sync_scheduler


def test_incremental_sync_scheduler_caps_requests(monkeypatch):
    calls: list[tuple[str, str]] = []

    def fake_sync_new_candles(*, symbol, timeframe, include_partial):
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

    def fake_sync_new_candles(*, symbol, timeframe, include_partial):
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
