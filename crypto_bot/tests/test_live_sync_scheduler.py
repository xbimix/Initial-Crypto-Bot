from __future__ import annotations

import json

from data import live_sync_scheduler


def setup_function():
    live_sync_scheduler._last_sync_at.clear()
    live_sync_scheduler._sync_job_stats.clear()
    live_sync_scheduler._watermark_loaded = True
    live_sync_scheduler._last_watermark_persist_epoch = 0.0
    live_sync_scheduler._background_timeframe_rr_index = 0
    live_sync_scheduler._last_tick_epoch = None


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
            "decision_candle_timeframe": "1d",
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
            "sync_reserved_requests_decision_timeframe": 1,
            "sync_max_background_share": 0.5,
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


def test_incremental_sync_scheduler_rotates_background_timeframes(monkeypatch):
    calls: list[tuple[str, str]] = []

    def fake_sync_new_candles(*, symbol, timeframe, include_partial, cfg=None):
        calls.append((symbol, timeframe))
        return {"requests": 1, "fetched": 1, "inserted": 1, "status": "ok"}

    monkeypatch.setattr(live_sync_scheduler, "sync_new_candles", fake_sync_new_candles)

    cfg = {
        "market_data": {
            "incremental_sync_enabled": True,
            "decision_candle_timeframe": "1m",
            "sync_timeframes": ["1m", "1h", "4h", "1d"],
            "sync_cadence_seconds": {"1m": 1, "1h": 1, "4h": 1, "1d": 1},
            "max_sync_requests_per_tick": 2,
            "sync_reserved_requests_decision_timeframe": 1,
            "sync_max_background_share": 0.5,
        }
    }

    for tick in range(6):
        live_sync_scheduler.run_incremental_sync_tick(
            cfg=cfg,
            symbols=["BTC-USD"],
            now_epoch=20_000.0 + tick,
        )

    background_timeframes = [tf for _, tf in calls if tf != "1m"]
    assert len(background_timeframes) >= 3
    assert {"1h", "4h", "1d"}.issubset(set(background_timeframes))


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
            "sync_reserved_requests_decision_timeframe": 0,
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


def test_incremental_sync_scheduler_reserves_decision_timeframe_capacity(monkeypatch):
    calls: list[tuple[str, str]] = []

    def fake_sync_new_candles(*, symbol, timeframe, include_partial, cfg=None):
        calls.append((symbol, timeframe))
        return {"requests": 1, "fetched": 1, "inserted": 1, "status": "ok"}

    monkeypatch.setattr(live_sync_scheduler, "sync_new_candles", fake_sync_new_candles)

    cfg = {
        "market_data": {
            "incremental_sync_enabled": True,
            "decision_candle_timeframe": "1m",
            "sync_timeframes": ["1m", "5m", "15m"],
            "sync_cadence_seconds": {"1m": 1, "5m": 1, "15m": 1},
            "max_sync_requests_per_tick": 4,
            "sync_reserved_requests_decision_timeframe": 3,
            "sync_max_background_share": 0.25,
        }
    }
    summary = live_sync_scheduler.run_incremental_sync_tick(
        cfg=cfg,
        symbols=["BTC-USD", "ETH-USD", "SOL-USD"],
        now_epoch=90_000.0,
    )

    scheduler = summary.get("scheduler", {})
    selected = scheduler.get("selected_jobs_by_timeframe", {})
    assert summary["attempted_jobs"] == 4
    assert selected.get("1m", 0) >= 3
    assert scheduler.get("decision_reservation_met") is True
    assert scheduler.get("selected_background_jobs", 0) <= 1


def test_incremental_sync_scheduler_reports_due_selected_and_starvation_telemetry(monkeypatch):
    def fake_sync_new_candles(*, symbol, timeframe, include_partial, cfg=None):
        return {"requests": 1, "fetched": 1, "inserted": 1, "status": "ok"}

    monkeypatch.setattr(live_sync_scheduler, "sync_new_candles", fake_sync_new_candles)

    cfg = {
        "market_data": {
            "incremental_sync_enabled": True,
            "decision_candle_timeframe": "1m",
            "sync_timeframes": ["1m", "5m"],
            "sync_cadence_seconds": {"1m": 1, "5m": 1},
            "max_sync_requests_per_tick": 1,
            "sync_reserved_requests_decision_timeframe": 1,
            "sync_max_background_share": 0.0,
        }
    }
    summary = live_sync_scheduler.run_incremental_sync_tick(
        cfg=cfg,
        symbols=["BTC-USD", "ETH-USD"],
        now_epoch=100_000.0,
    )
    scheduler = summary.get("scheduler", {})
    assert scheduler.get("due_jobs_total", 0) >= 1
    assert scheduler.get("selected_jobs_total", 0) == 1
    assert "due_jobs_by_timeframe" in scheduler
    assert "selected_jobs_by_timeframe" in scheduler
    assert "skipped_due_jobs_by_timeframe" in scheduler
    assert "oldest_due_age_seconds_by_timeframe" in scheduler


def test_incremental_sync_scheduler_always_includes_decision_timeframe(monkeypatch):
    calls: list[tuple[str, str]] = []

    def fake_sync_new_candles(*, symbol, timeframe, include_partial, cfg=None):
        calls.append((symbol, timeframe))
        return {"requests": 1, "fetched": 1, "inserted": 1, "status": "ok"}

    monkeypatch.setattr(live_sync_scheduler, "sync_new_candles", fake_sync_new_candles)
    cfg = {
        "market_data": {
            "incremental_sync_enabled": True,
            "decision_candle_timeframe": "1m",
            "sync_timeframes": ["1h", "4h"],
            "sync_cadence_seconds": {"1m": 1, "1h": 1, "4h": 1},
            "max_sync_requests_per_tick": 3,
            "sync_reserved_requests_decision_timeframe": 1,
        }
    }
    summary = live_sync_scheduler.run_incremental_sync_tick(
        cfg=cfg,
        symbols=["BTC-USD"],
        now_epoch=120_000.0,
    )
    scheduler = summary.get("scheduler", {})
    assert scheduler.get("due_jobs_by_timeframe", {}).get("1m", 0) >= 1
    assert scheduler.get("selected_jobs_by_timeframe", {}).get("1m", 0) >= 1


def test_incremental_sync_scheduler_applies_stale_symbol_catchup_priority(monkeypatch):
    calls: list[tuple[str, str]] = []

    def fake_sync_new_candles(*, symbol, timeframe, include_partial, cfg=None):
        calls.append((symbol, timeframe))
        return {"requests": 1, "fetched": 1, "inserted": 1, "status": "ok"}

    monkeypatch.setattr(live_sync_scheduler, "sync_new_candles", fake_sync_new_candles)
    now = 140_000.0
    live_sync_scheduler._last_sync_at.update(
        {
            ("BTC-USD", "1m"): now - 130.0,  # stale candidate (>= 6 intervals at 20s cadence)
            ("BTC-USD", "5m"): now - 10.0,   # not due
            ("ETH-USD", "1m"): now - 30.0,   # due but not stale
            ("ETH-USD", "5m"): now - 300.0,  # very old background due
            ("SOL-USD", "1m"): now - 30.0,   # due but not stale
            ("SOL-USD", "5m"): now - 290.0,  # very old background due
        }
    )
    cfg = {
        "market_data": {
            "incremental_sync_enabled": True,
            "decision_candle_timeframe": "1m",
            "sync_timeframes": ["1m", "5m"],
            "sync_cadence_seconds": {"1m": 20, "5m": 20},
            "max_sync_requests_per_tick": 2,
            "sync_reserved_requests_decision_timeframe": 0,
            "sync_max_background_share": 1.0,
            "sync_stale_catchup_enabled": True,
            "sync_stale_catchup_age_intervals": 6,
            "sync_stale_catchup_reserved_requests": 1,
            "sync_stale_catchup_max_symbols": 2,
        }
    }

    summary = live_sync_scheduler.run_incremental_sync_tick(
        cfg=cfg,
        symbols=["BTC-USD", "ETH-USD", "SOL-USD"],
        now_epoch=now,
    )
    scheduler = summary.get("scheduler", {})
    assert ("BTC-USD", "1m") in calls
    assert scheduler.get("stale_catchup_selected_jobs", 0) >= 1
    assert "BTC-USD" in scheduler.get("stale_catchup_candidate_symbols", [])


def test_incremental_sync_scheduler_does_not_trigger_stale_catchup_below_threshold(monkeypatch):
    calls: list[tuple[str, str]] = []

    def fake_sync_new_candles(*, symbol, timeframe, include_partial, cfg=None):
        calls.append((symbol, timeframe))
        return {"requests": 1, "fetched": 1, "inserted": 1, "status": "ok"}

    monkeypatch.setattr(live_sync_scheduler, "sync_new_candles", fake_sync_new_candles)
    now = 150_000.0
    live_sync_scheduler._last_sync_at.update(
        {
            ("BTC-USD", "1m"): now - 80.0,   # due but not stale for threshold=6*20s
            ("ETH-USD", "5m"): now - 300.0,  # old background due
            ("SOL-USD", "5m"): now - 290.0,  # old background due
            ("ETH-USD", "1m"): now - 30.0,
            ("SOL-USD", "1m"): now - 30.0,
        }
    )
    cfg = {
        "market_data": {
            "incremental_sync_enabled": True,
            "decision_candle_timeframe": "1m",
            "sync_timeframes": ["1m", "5m"],
            "sync_cadence_seconds": {"1m": 20, "5m": 20},
            "max_sync_requests_per_tick": 2,
            "sync_reserved_requests_decision_timeframe": 0,
            "sync_max_background_share": 1.0,
            "sync_stale_catchup_enabled": True,
            "sync_stale_catchup_age_intervals": 6,
            "sync_stale_catchup_reserved_requests": 1,
            "sync_stale_catchup_max_symbols": 2,
        }
    }

    summary = live_sync_scheduler.run_incremental_sync_tick(
        cfg=cfg,
        symbols=["BTC-USD", "ETH-USD", "SOL-USD"],
        now_epoch=now,
    )
    scheduler = summary.get("scheduler", {})
    assert ("BTC-USD", "1m") not in calls
    assert scheduler.get("stale_catchup_selected_jobs", 0) == 0


def test_incremental_sync_scheduler_applies_decision_specific_fallback_policy(monkeypatch):
    calls: list[dict] = []

    def fake_sync_new_candles(
        *,
        symbol,
        timeframe,
        include_partial,
        cfg=None,
        allow_public_fallback=None,
        allow_snapshot_fallback=None,
    ):
        calls.append(
            {
                "symbol": symbol,
                "timeframe": timeframe,
                "allow_public_fallback": allow_public_fallback,
                "allow_snapshot_fallback": allow_snapshot_fallback,
            }
        )
        return {"requests": 1, "fetched": 1, "inserted": 1, "status": "ok"}

    monkeypatch.setattr(live_sync_scheduler, "sync_new_candles", fake_sync_new_candles)
    cfg = {
        "market_data": {
            "incremental_sync_enabled": True,
            "decision_candle_timeframe": "1m",
            "sync_timeframes": ["1m", "5m"],
            "sync_cadence_seconds": {"1m": 1, "5m": 1},
            "max_sync_requests_per_tick": 2,
            "source_map": {
                "candles": {
                    "allow_public_fallback": True,
                    "allow_snapshot_fallback": True,
                    "decision_use_public_fallback": False,
                    "decision_use_snapshot_fallback": False,
                }
            },
        }
    }

    live_sync_scheduler.run_incremental_sync_tick(
        cfg=cfg,
        symbols=["BTC-USD"],
        now_epoch=200_000.0,
    )

    by_tf = {row["timeframe"]: row for row in calls}
    assert by_tf["1m"]["allow_public_fallback"] is False
    assert by_tf["1m"]["allow_snapshot_fallback"] is False
    assert by_tf["5m"]["allow_public_fallback"] is True
    assert by_tf["5m"]["allow_snapshot_fallback"] is True


def test_incremental_sync_scheduler_persists_and_restores_watermark(tmp_path, monkeypatch):
    watermark_path = tmp_path / "scheduler_sync_watermark.json"
    monkeypatch.setattr(live_sync_scheduler, "SCHEDULER_WATERMARK_PATH", watermark_path)

    def fake_sync_new_candles(*, symbol, timeframe, include_partial, cfg=None):
        return {"requests": 1, "fetched": 1, "inserted": 1, "status": "ok"}

    monkeypatch.setattr(live_sync_scheduler, "sync_new_candles", fake_sync_new_candles)

    cfg = {
        "market_data": {
            "incremental_sync_enabled": True,
            "decision_candle_timeframe": "1m",
            "sync_timeframes": ["1m"],
            "sync_cadence_seconds": {"1m": 1},
            "max_sync_requests_per_tick": 1,
            "sync_persist_watermark_enabled": True,
            "sync_watermark_persist_interval_seconds": 1,
            "sync_watermark_ttl_seconds": 3600,
            "sync_watermark_max_entries": 1000,
        }
    }

    first = live_sync_scheduler.run_incremental_sync_tick(
        cfg=cfg,
        symbols=["BTC-USD"],
        now_epoch=300_000.0,
    )
    assert first["scheduler"]["watermark_persisted"] is True
    assert watermark_path.exists()

    live_sync_scheduler._last_sync_at.clear()
    live_sync_scheduler._watermark_loaded = False
    second = live_sync_scheduler.run_incremental_sync_tick(
        cfg=cfg,
        symbols=[],
        now_epoch=300_000.5,
    )
    assert second["scheduler"]["watermark_restore_entries"] >= 1


def test_incremental_sync_scheduler_ignores_expired_watermark_entries(tmp_path, monkeypatch):
    watermark_path = tmp_path / "scheduler_sync_watermark.json"
    payload = {
        "updated_at_epoch": 1_000.0,
        "entries": [
            {
                "symbol": "BTC-USD",
                "timeframe": "1m",
                "last_sync_at": 100.0,
            }
        ],
    }
    watermark_path.write_text(json.dumps(payload), encoding="utf-8")
    monkeypatch.setattr(live_sync_scheduler, "SCHEDULER_WATERMARK_PATH", watermark_path)

    def fake_sync_new_candles(*, symbol, timeframe, include_partial, cfg=None):
        return {"requests": 1, "fetched": 1, "inserted": 1, "status": "ok"}

    monkeypatch.setattr(live_sync_scheduler, "sync_new_candles", fake_sync_new_candles)
    live_sync_scheduler._last_sync_at.clear()
    live_sync_scheduler._watermark_loaded = False
    cfg = {
        "market_data": {
            "incremental_sync_enabled": True,
            "decision_candle_timeframe": "1m",
            "sync_timeframes": ["1m"],
            "sync_cadence_seconds": {"1m": 60},
            "max_sync_requests_per_tick": 1,
            "sync_persist_watermark_enabled": True,
            "sync_watermark_ttl_seconds": 60,
        }
    }

    summary = live_sync_scheduler.run_incremental_sync_tick(
        cfg=cfg,
        symbols=[],
        now_epoch=10_000.0,
    )
    assert summary["scheduler"]["watermark_restore_entries"] == 0


def test_incremental_sync_scheduler_auto_scales_request_cap_for_decision_freshness(monkeypatch):
    calls: list[tuple[str, str]] = []

    def fake_sync_new_candles(*, symbol, timeframe, include_partial, cfg=None):
        calls.append((symbol, timeframe))
        return {"requests": 1, "fetched": 1, "inserted": 1, "status": "ok"}

    monkeypatch.setattr(live_sync_scheduler, "sync_new_candles", fake_sync_new_candles)

    symbols = [f"T{i:02d}-USD" for i in range(1, 41)]
    cfg = {
        "market_data": {
            "incremental_sync_enabled": True,
            "decision_candle_timeframe": "1m",
            "sync_timeframes": ["1m", "1h"],
            "sync_cadence_seconds": {"1m": 1, "1h": 1},
            "max_sync_requests_per_tick": 4,
            "sync_auto_scale_requests_enabled": True,
            "sync_auto_scale_requests_max_per_tick": 12,
            "sync_target_decision_freshness_seconds": 60,
            "sync_assumed_tick_seconds": 12,
            "sync_min_background_jobs_per_tick": 1,
        }
    }

    summary = live_sync_scheduler.run_incremental_sync_tick(
        cfg=cfg,
        symbols=symbols,
        now_epoch=410_000.0,
    )
    scheduler = summary.get("scheduler", {})
    assert scheduler.get("request_cap_base") == 4
    assert scheduler.get("request_cap") == 9
    assert scheduler.get("decision_jobs_required_for_target") == 8
    assert scheduler.get("reserved_requests_decision_timeframe") >= 8
    assert summary.get("attempted_jobs") == 9
    assert len(calls) == 9


def test_incremental_sync_scheduler_auto_scale_can_be_disabled(monkeypatch):
    calls: list[tuple[str, str]] = []

    def fake_sync_new_candles(*, symbol, timeframe, include_partial, cfg=None):
        calls.append((symbol, timeframe))
        return {"requests": 1, "fetched": 1, "inserted": 1, "status": "ok"}

    monkeypatch.setattr(live_sync_scheduler, "sync_new_candles", fake_sync_new_candles)

    symbols = [f"T{i:02d}-USD" for i in range(1, 41)]
    cfg = {
        "market_data": {
            "incremental_sync_enabled": True,
            "decision_candle_timeframe": "1m",
            "sync_timeframes": ["1m", "1h"],
            "sync_cadence_seconds": {"1m": 1, "1h": 1},
            "max_sync_requests_per_tick": 4,
            "sync_auto_scale_requests_enabled": False,
            "sync_auto_scale_requests_max_per_tick": 12,
            "sync_target_decision_freshness_seconds": 60,
            "sync_assumed_tick_seconds": 12,
            "sync_min_background_jobs_per_tick": 1,
        }
    }

    summary = live_sync_scheduler.run_incremental_sync_tick(
        cfg=cfg,
        symbols=symbols,
        now_epoch=420_000.0,
    )
    scheduler = summary.get("scheduler", {})
    assert scheduler.get("request_cap") == 4
    assert scheduler.get("request_cap_auto_scale_enabled") is False
    assert summary.get("attempted_jobs") == 4
    assert len(calls) == 4


def test_incremental_sync_scheduler_ingestion_guard_reports_degraded_when_oldest_due_exceeds_target(monkeypatch):
    def fake_sync_new_candles(*, symbol, timeframe, include_partial, cfg=None):
        return {"requests": 1, "fetched": 1, "inserted": 1, "status": "ok"}

    monkeypatch.setattr(live_sync_scheduler, "sync_new_candles", fake_sync_new_candles)
    now = 500_000.0
    live_sync_scheduler._last_sync_at.update(
        {
            ("BTC-USD", "1m"): now - 250.0,
            ("ETH-USD", "1m"): now - 240.0,
            ("SOL-USD", "1m"): now - 230.0,
        }
    )
    cfg = {
        "market_data": {
            "incremental_sync_enabled": True,
            "decision_candle_timeframe": "1m",
            "sync_timeframes": ["1m"],
            "sync_cadence_seconds": {"1m": 20},
            "max_sync_requests_per_tick": 1,
            "sync_target_decision_freshness_seconds": 90,
            "sync_auto_scale_requests_enabled": False,
        }
    }

    summary = live_sync_scheduler.run_incremental_sync_tick(
        cfg=cfg,
        symbols=["BTC-USD", "ETH-USD", "SOL-USD"],
        now_epoch=now,
    )
    guard = (summary.get("scheduler", {}) or {}).get("ingestion_guard", {})
    assert guard.get("status") == "DEGRADED"
    reasons = set(guard.get("reasons", []))
    assert "decision_oldest_due_exceeds_target" in reasons


def test_incremental_sync_scheduler_ingestion_guard_reports_ok_when_decision_service_is_healthy(monkeypatch):
    def fake_sync_new_candles(*, symbol, timeframe, include_partial, cfg=None):
        return {"requests": 1, "fetched": 1, "inserted": 1, "status": "ok"}

    monkeypatch.setattr(live_sync_scheduler, "sync_new_candles", fake_sync_new_candles)
    cfg = {
        "market_data": {
            "incremental_sync_enabled": True,
            "decision_candle_timeframe": "1m",
            "sync_timeframes": ["1m"],
            "sync_cadence_seconds": {"1m": 1},
            "max_sync_requests_per_tick": 3,
            "sync_target_decision_freshness_seconds": 90,
            "sync_auto_scale_requests_enabled": False,
            "sync_reserved_requests_decision_timeframe": 3,
        }
    }

    summary = live_sync_scheduler.run_incremental_sync_tick(
        cfg=cfg,
        symbols=["BTC-USD", "ETH-USD", "SOL-USD"],
        now_epoch=510_000.0,
    )
    guard = (summary.get("scheduler", {}) or {}).get("ingestion_guard", {})
    assert guard.get("status") == "OK"
    assert guard.get("reasons") == []


def test_incremental_sync_scheduler_emits_decision_timeframe_metrics_rows(monkeypatch):
    def fake_sync_new_candles(*, symbol, timeframe, include_partial, cfg=None):
        return {"requests": 1, "fetched": 1, "inserted": 1, "status": "ok"}

    monkeypatch.setattr(live_sync_scheduler, "sync_new_candles", fake_sync_new_candles)
    cfg = {
        "market_data": {
            "incremental_sync_enabled": True,
            "decision_candle_timeframe": "1m",
            "sync_timeframes": ["1m"],
            "sync_cadence_seconds": {"1m": 1},
            "max_sync_requests_per_tick": 1,
            "sync_target_decision_freshness_seconds": 90,
        }
    }

    live_sync_scheduler.run_incremental_sync_tick(
        cfg=cfg,
        symbols=["BTC-USD"],
        now_epoch=520_000.0,
    )
    summary = live_sync_scheduler.run_incremental_sync_tick(
        cfg=cfg,
        symbols=["BTC-USD"],
        now_epoch=520_010.0,
    )
    metrics = ((summary.get("scheduler", {}) or {}).get("decision_timeframe_metrics", {}) or {})
    rows = metrics.get("rows", [])
    assert metrics.get("symbols_total") == 1
    assert len(rows) == 1
    row = rows[0]
    assert row.get("symbol") == "BTC-USD"
    assert isinstance(row.get("last_sync_at_epoch"), float)
    assert isinstance(row.get("age_seconds"), float)
    assert row.get("update_frequency_per_hour") is not None
    assert row.get("attempts", 0) >= 2
    assert row.get("successes", 0) >= 2


def test_incremental_sync_scheduler_enforces_min_background_jobs_when_auto_scale_off(monkeypatch):
    def fake_sync_new_candles(*, symbol, timeframe, include_partial, cfg=None):
        return {"requests": 1, "fetched": 1, "inserted": 1, "status": "ok"}

    monkeypatch.setattr(live_sync_scheduler, "sync_new_candles", fake_sync_new_candles)
    cfg = {
        "market_data": {
            "incremental_sync_enabled": True,
            "decision_candle_timeframe": "1m",
            "sync_timeframes": ["1m", "1h", "4h"],
            "sync_cadence_seconds": {"1m": 1, "1h": 1, "4h": 1},
            "max_sync_requests_per_tick": 4,
            "sync_auto_scale_requests_enabled": False,
            "sync_reserved_requests_decision_timeframe": 4,
            "sync_stale_catchup_enabled": False,
            "sync_min_background_jobs_per_tick": 2,
        }
    }

    summary = live_sync_scheduler.run_incremental_sync_tick(
        cfg=cfg,
        symbols=[f"T{i:02d}-USD" for i in range(1, 16)],
        now_epoch=530_000.0,
    )
    scheduler = summary.get("scheduler", {})
    selected = scheduler.get("selected_jobs_by_timeframe", {})
    background_selected = int(selected.get("1h", 0) or 0) + int(selected.get("4h", 0) or 0)
    assert background_selected >= 2
    assert scheduler.get("required_background_jobs") == 2
    assert scheduler.get("max_decision_slots") == 2
    assert int(scheduler.get("decision_selected_jobs", 0) or 0) <= 2


def test_incremental_sync_scheduler_caps_decision_reservations_when_background_is_degraded(monkeypatch):
    def fake_sync_new_candles(*, symbol, timeframe, include_partial, cfg=None):
        return {"requests": 1, "fetched": 1, "inserted": 1, "status": "ok"}

    monkeypatch.setattr(live_sync_scheduler, "sync_new_candles", fake_sync_new_candles)

    now = 540_000.0
    symbols = ["BTC-USD", "ETH-USD", "SOL-USD"]
    for symbol in symbols:
        live_sync_scheduler._last_sync_at[(symbol, "1m")] = now - 120.0
        live_sync_scheduler._last_sync_at[(symbol, "1h")] = now - 600.0

    cfg = {
        "market_data": {
            "incremental_sync_enabled": True,
            "decision_candle_timeframe": "1m",
            "sync_timeframes": ["1m", "1h"],
            "sync_cadence_seconds": {"1m": 60, "1h": 60},
            "max_sync_requests_per_tick": 3,
            "sync_auto_scale_requests_enabled": False,
            "sync_reserved_requests_decision_timeframe": 3,
            "sync_stale_catchup_enabled": True,
            "sync_stale_catchup_age_intervals": 1,
            "sync_stale_catchup_reserved_requests": 3,
            "sync_min_background_jobs_per_tick": 0,
        }
    }

    summary = live_sync_scheduler.run_incremental_sync_tick(
        cfg=cfg,
        symbols=symbols,
        now_epoch=now,
    )
    scheduler = summary.get("scheduler", {})
    selected = scheduler.get("selected_jobs_by_timeframe", {})

    assert scheduler.get("background_degraded") is True
    assert scheduler.get("required_background_jobs") == 1
    assert int(selected.get("1h", 0) or 0) >= 1
    assert int(scheduler.get("decision_reserved_slots_total", 0) or 0) <= 2
