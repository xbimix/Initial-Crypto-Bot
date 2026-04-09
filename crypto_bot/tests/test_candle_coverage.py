from __future__ import annotations

import importlib
from pathlib import Path

from data import candle_coverage
from data import revolut_market_db


def test_summarize_core_timeframe_coverage(tmp_path: Path):
    db_path = tmp_path / "market_data.db"
    now_ms = 1_000_000
    revolut_market_db.upsert_candles(
        "BTC-USD",
        "1h",
        [
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
        source="revolut",
    )
    revolut_market_db.upsert_sync_state(
        "BTC-USD",
        "1h",
        earliest_ms=now_ms - (2 * 3_600_000),
        latest_ms=now_ms - (2 * 3_600_000),
        last_sync_ms=now_ms,
        status="ok",
        note="unit_test",
        db_path=db_path,
    )

    summary = candle_coverage.summarize_core_timeframe_coverage(
        db_path=db_path,
        now_ms=now_ms,
    )
    assert summary["status_counts"].get("ok", 0) == 1
    assert summary["fresh_counts_by_timeframe"]["1h"] == 1
    assert summary["total_rows"] == 1


def test_default_db_path_resolves_into_runtime_state_dir(monkeypatch, tmp_path: Path):
    monkeypatch.setenv("BOT_DATA_DIR", str(tmp_path / "runtime_root"))
    monkeypatch.delenv("REVBOT_STATE_DIR", raising=False)
    reloaded = importlib.reload(candle_coverage)
    assert "runtime_root" in str(reloaded.DEFAULT_DB_PATH)
    assert reloaded.DEFAULT_DB_PATH.name == "market_data.db"
