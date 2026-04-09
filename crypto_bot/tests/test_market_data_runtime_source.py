from __future__ import annotations

from data import market_data


def _mock_order_book():
    return {
        "data": {
            "bids": [
                {"aid": "BTC", "pc": "USD", "qc": "BTC", "s": "BUYI", "p": "99.0", "q": "5"},
                {"aid": "BTC", "pc": "USD", "qc": "BTC", "s": "BUYI", "p": "98.5", "q": "4"},
            ],
            "asks": [
                {"aid": "BTC", "pc": "USD", "qc": "BTC", "s": "SELL", "p": "100.0", "q": "5"},
                {"aid": "BTC", "pc": "USD", "qc": "BTC", "s": "SELL", "p": "100.5", "q": "4"},
            ],
        },
        "metadata": {"timestamp": "2026-03-20T03:00:00Z"},
    }


def test_fetch_market_snapshot_prefers_sqlite_candles(monkeypatch):
    monkeypatch.setattr(market_data, "get_order_book", lambda symbol, cfg=None: _mock_order_book())
    monkeypatch.setattr(market_data, "get_last_trades", lambda symbol, limit: [])
    monkeypatch.setattr(market_data, "sync_new_candles", lambda **kwargs: {"inserted": 0})
    monkeypatch.setattr(
        market_data,
        "get_candles",
        lambda symbol, timeframe, limit: [
            {
                "open_time": idx * 60_000,
                "close": 100.0 + (idx * 0.05),
                "volume": 10.0,
            }
            for idx in range(120)
        ],
    )
    monkeypatch.setattr(
        market_data,
        "get_candle_meta",
        lambda symbol, timeframe: {"stale": False, "supported": True},
    )

    cfg = {
        "lookback": 200,
        "market_data": {
            "min_history_points": 8,
            "decision_candle_timeframe": "1m",
            "decision_candle_sync_enabled": True,
        },
    }
    snapshot = market_data.fetch_market_snapshot("BTC-USD", cfg)
    assert snapshot is not None
    assert snapshot["history_source"] == "sqlite_candles"
    assert snapshot["sampling_minutes"] == 1.0
    assert len(snapshot["recent_prices"]) == 60
    assert snapshot["snapshot_ts_epoch"] > 0


def test_fetch_market_snapshot_falls_back_to_stream_history(monkeypatch):
    monkeypatch.setattr(market_data, "get_order_book", lambda symbol, cfg=None: _mock_order_book())
    monkeypatch.setattr(market_data, "get_last_trades", lambda symbol, limit: [])
    monkeypatch.setattr(market_data, "sync_new_candles", lambda **kwargs: {"inserted": 0})
    monkeypatch.setattr(market_data, "get_candles", lambda symbol, timeframe, limit: [])
    monkeypatch.setattr(
        market_data,
        "get_candle_meta",
        lambda symbol, timeframe: {"stale": True, "supported": False},
    )

    cfg = {
        "lookback": 200,
        "market_data": {
            "min_history_points": 1,
            "decision_candle_timeframe": "1m",
            "decision_candle_sync_enabled": False,
        },
    }
    snapshot = market_data.fetch_market_snapshot("BTC-USD", cfg)
    assert snapshot is not None
    assert snapshot["history_source"] == "order_book_stream"


def test_indicator_features_reuse_cache_until_new_closed_candle(monkeypatch):
    market_data._INDICATOR_CACHE.clear()
    monkeypatch.setattr(market_data, "get_order_book", lambda symbol, cfg=None: _mock_order_book())
    monkeypatch.setattr(market_data, "get_last_trades", lambda symbol, limit: [])
    monkeypatch.setattr(market_data, "sync_new_candles", lambda **kwargs: {"inserted": 0})
    monkeypatch.setattr(
        market_data,
        "get_candles",
        lambda symbol, timeframe, limit: [
            {"open_time": idx * 60_000, "close": 100.0 + (idx * 0.05), "volume": 10.0}
            for idx in range(120)
        ],
    )
    monkeypatch.setattr(
        market_data,
        "get_candle_meta",
        lambda symbol, timeframe: {
            "stale": False,
            "supported": True,
            "latest_open_time": 7_200_000,
        },
    )
    calls = {"n": 0}

    def _counted_rsi(prices, period=14):
        calls["n"] += 1
        return 55.0

    monkeypatch.setattr(market_data, "calculate_rsi", _counted_rsi)
    cfg = {
        "lookback": 200,
        "market_data": {"min_history_points": 8, "decision_candle_timeframe": "1m"},
    }

    a = market_data.fetch_market_snapshot("BTC-USD", cfg)
    b = market_data.fetch_market_snapshot("BTC-USD", cfg)
    assert a is not None and b is not None
    assert calls["n"] == 1


def test_indicator_features_recompute_when_latest_closed_candle_changes(monkeypatch):
    market_data._INDICATOR_CACHE.clear()
    monkeypatch.setattr(market_data, "get_order_book", lambda symbol, cfg=None: _mock_order_book())
    monkeypatch.setattr(market_data, "get_last_trades", lambda symbol, limit: [])
    monkeypatch.setattr(market_data, "sync_new_candles", lambda **kwargs: {"inserted": 0})
    monkeypatch.setattr(
        market_data,
        "get_candles",
        lambda symbol, timeframe, limit: [
            {"open_time": idx * 60_000, "close": 100.0 + (idx * 0.05), "volume": 10.0}
            for idx in range(120)
        ],
    )
    latest_values = [7_200_000, 7_260_000]

    def _meta(symbol, timeframe):
        return {
            "stale": False,
            "supported": True,
            "latest_open_time": latest_values.pop(0) if latest_values else 7_260_000,
        }

    monkeypatch.setattr(market_data, "get_candle_meta", _meta)
    calls = {"n": 0}

    def _counted_rsi(prices, period=14):
        calls["n"] += 1
        return 55.0

    monkeypatch.setattr(market_data, "calculate_rsi", _counted_rsi)
    cfg = {
        "lookback": 200,
        "market_data": {"min_history_points": 8, "decision_candle_timeframe": "1m"},
    }

    a = market_data.fetch_market_snapshot("BTC-USD", cfg)
    b = market_data.fetch_market_snapshot("BTC-USD", cfg)
    assert a is not None and b is not None
    assert calls["n"] == 2


def test_fetch_market_snapshot_falls_back_to_hl_range_for_flat_close_atr(monkeypatch):
    monkeypatch.setattr(market_data, "get_order_book", lambda symbol, cfg=None: _mock_order_book())
    monkeypatch.setattr(market_data, "get_last_trades", lambda symbol, limit: [])
    monkeypatch.setattr(market_data, "sync_new_candles", lambda **kwargs: {"inserted": 0})
    monkeypatch.setattr(
        market_data,
        "get_candles",
        lambda symbol, timeframe, limit: [
            {
                "open_time": idx * 60_000,
                "close": 100.0,
                "high": 101.0,
                "low": 99.0,
                "volume": 10.0,
            }
            for idx in range(160)
        ],
    )
    monkeypatch.setattr(
        market_data,
        "get_candle_meta",
        lambda symbol, timeframe: {
            "stale": False,
            "supported": True,
            "latest_open_time": 9_540_000,
            "age_seconds": 45.0,
        },
    )
    cfg = {
        "lookback": 200,
        "market_data": {
            "min_history_points": 8,
            "decision_candle_timeframe": "1m",
            "decision_candle_sync_enabled": False,
        },
    }
    snapshot = market_data.fetch_market_snapshot("BTC-USD", cfg)
    assert snapshot is not None
    assert snapshot["history_source"] == "sqlite_candles"
    assert snapshot["atr_raw"] > 0.0
    assert snapshot["atr_pct"] == snapshot["atr_raw"]
