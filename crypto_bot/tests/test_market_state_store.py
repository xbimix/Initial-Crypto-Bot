from __future__ import annotations

import time

from data import market_data
from data.state_store import MarketDataStateStore


def test_snapshot_merge_tracks_field_timestamps_and_versions():
    store = MarketDataStateStore()

    first = store.merge_snapshot_fields(
        symbol="btc-usd",
        fields={"price": 100.0, "spread_bps": 12.0},
        snapshot_ts_epoch=10.0,
        quality_state="tradable",
    )
    second = store.merge_snapshot_fields(
        symbol="BTC-USD",
        fields={"price": 100.0, "spread_bps": 12.0},
        snapshot_ts_epoch=20.0,
        quality_state="tradable",
    )
    third = store.merge_snapshot_fields(
        symbol="BTC-USD",
        fields={"price": 101.0, "spread_bps": 12.0},
        snapshot_ts_epoch=30.0,
        quality_state="degraded",
    )

    assert first.version == 1
    assert first.state_changed is True
    assert first.field_timestamps["price"] == 10.0
    assert second.version == 2
    assert second.state_changed is False
    assert second.field_timestamps["price"] == 10.0
    assert third.version == 3
    assert third.state_changed is True
    assert third.changed_fields == ("price",)
    assert third.field_timestamps["price"] == 30.0
    assert third.quality_state == "DEGRADED"


def test_market_quality_classification_states():
    ok, reason, status, state = market_data._classify_market_quality([], history_points=120)
    assert ok is True
    assert reason == "ok"
    assert status == "GOOD"
    assert state == "TRADABLE"

    ok, reason, status, state = market_data._classify_market_quality(
        ["spread_too_wide"],
        history_points=120,
    )
    assert ok is False
    assert "spread_too_wide" in reason
    assert status == "PARTIAL"
    assert state == "DEGRADED"

    ok, reason, status, state = market_data._classify_market_quality(
        ["candle_history_stale"],
        history_points=120,
    )
    assert ok is False
    assert "candle_history_stale" in reason
    assert status == "STALE"
    assert state == "UNSAFE"


def test_strategy_eval_gate_blocks_stale_snapshot():
    snapshot = {
        "symbol": "BTC-USD",
        "data_quality_status": "GOOD",
        "data_quality_state": "TRADABLE",
        "snapshot_ts_epoch": time.time() - 120.0,
        "core_candle_readiness": {"ready": True},
    }
    gate = market_data._build_strategy_eval_gate(
        snapshot,
        {"market_data": {"strict_strategy_eval_gate_enabled": True, "strategy_eval_max_snapshot_age_seconds": 10}},
    )
    assert gate.allowed is False
    assert gate.blocked_reason == "market_snapshot_stale"


def test_strategy_eval_gate_allows_fresh_good_snapshot():
    snapshot = {
        "symbol": "BTC-USD",
        "data_quality_status": "GOOD",
        "data_quality_state": "TRADABLE",
        "snapshot_ts_epoch": time.time(),
        "core_candle_readiness": {"ready": True},
    }
    gate = market_data._build_strategy_eval_gate(
        snapshot,
        {"market_data": {"strict_strategy_eval_gate_enabled": True, "strategy_eval_max_snapshot_age_seconds": 60}},
    )
    assert gate.allowed is True
    assert gate.blocked_reason is None


def test_fetch_market_snapshot_reuses_cached_candle_history_and_indicators(monkeypatch):
    market_data._STATE_STORE.clear()
    market_data._INDICATOR_CACHE.clear()

    def _book():
        return {
            "data": {
                "bids": [{"aid": "BTC", "pc": "USD", "qc": "BTC", "s": "BUYI", "p": "99.0", "q": "5"}],
                "asks": [{"aid": "BTC", "pc": "USD", "qc": "BTC", "s": "SELL", "p": "100.0", "q": "5"}],
            },
            "metadata": {"timestamp": "2026-03-20T03:00:00Z"},
        }

    monkeypatch.setattr(market_data, "get_order_book", lambda symbol, cfg=None: _book())
    monkeypatch.setattr(market_data, "get_last_trades", lambda symbol, limit: [])
    monkeypatch.setattr(market_data, "sync_new_candles", lambda **kwargs: {"inserted": 0})
    candle_calls = {"n": 0}
    rsi_calls = {"n": 0}

    def _candles(symbol, timeframe, limit):
        candle_calls["n"] += 1
        return [
            {"open_time": idx * 60_000, "close": 100.0 + (idx * 0.05), "volume": 10.0}
            for idx in range(140)
        ]

    def _rsi(prices, period=14):
        rsi_calls["n"] += 1
        return 55.0

    monkeypatch.setattr(market_data, "get_candles", _candles)
    monkeypatch.setattr(
        market_data,
        "get_candle_meta",
        lambda symbol, timeframe: {"stale": False, "supported": True, "latest_open_time": 8_400_000},
    )
    monkeypatch.setattr(market_data, "calculate_rsi", _rsi)

    cfg = {"lookback": 200, "market_data": {"min_history_points": 8, "decision_candle_timeframe": "1m"}}
    first = market_data.fetch_market_snapshot("BTC-USD", cfg)
    second = market_data.fetch_market_snapshot("BTC-USD", cfg)

    assert first is not None
    assert second is not None
    assert candle_calls["n"] == 1
    assert rsi_calls["n"] == 1
    assert first["snapshot_version"] == 1
    assert second["snapshot_version"] == 2
