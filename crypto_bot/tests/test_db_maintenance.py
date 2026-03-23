from __future__ import annotations

from pathlib import Path

from data.db_maintenance import run_db_maintenance
from data.revolut_market_db import get_candle_count, upsert_candles


def test_db_maintenance_trims_and_reports(tmp_path: Path):
    db_path = tmp_path / "market_data.db"
    symbol = "BTC-USD"
    tf = "1m"
    interval_ms = 60_000
    candles = []
    for idx in range(60 * 24 * 3):  # 3 days of 1m bars
        ts = idx * interval_ms
        candles.append(
            {
                "ts": ts,
                "open": 100.0,
                "high": 101.0,
                "low": 99.0,
                "close": 100.0,
                "volume": 1.0,
                "close_time": ts + interval_ms - 1,
            }
        )
    upsert_candles(symbol=symbol, timeframe=tf, candles=candles, db_path=db_path)
    before = get_candle_count(symbol=symbol, timeframe=tf, db_path=db_path)
    assert before > 1000

    report = run_db_maintenance(
        cfg={"market_data": {"retention_days_by_timeframe": {"1m": 1}}},
        db_path=db_path,
    )
    after = get_candle_count(symbol=symbol, timeframe=tf, db_path=db_path)
    assert report["rows_after"] >= after
    assert after < before
    assert report["trimmed_rows"] >= 1

