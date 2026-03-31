from __future__ import annotations

from data.decision_input_builder import build_decision_context
from data.feature_engine import resolve_indicator_features
from data.ingestion import fetch_order_book_update, fetch_trade_updates
from data.state_store import MarketDataStateStore


def test_ingestion_order_book_normalizes_and_rejects_malformed_rows():
    def _fake_order_book(symbol, cfg=None):
        assert symbol == "BTC-USD"
        return {
            "data": {
                "bids": [
                    {"aid": "BTC", "pc": "USD", "qc": "BTC", "s": "BUYI", "p": "99.5", "q": "2"},
                    {"aid": "BTC", "pc": "USD", "qc": "BTC", "s": "BUYI", "p": "bad", "q": "2"},
                ],
                "asks": [
                    {"aid": "BTC", "pc": "USD", "qc": "BTC", "s": "SELL", "p": "100.5", "q": "2"},
                    {"aid": "ETH", "pc": "USD", "qc": "ETH", "s": "SELL", "p": "101.0", "q": "2"},
                ],
            },
            "metadata": {"timestamp": "2026-03-20T03:00:00Z"},
        }

    update = fetch_order_book_update("btc-usd", fetcher=_fake_order_book)
    assert update is not None
    assert update.symbol == "BTC-USD"
    assert len(update.bids) == 1
    assert len(update.asks) == 1
    assert update.bids[0].price == 99.5
    assert update.asks[0].price == 100.5


def test_ingestion_trade_updates_filter_invalid_payload():
    def _fake_trades(symbol, limit):
        assert symbol == "BTC-USD"
        assert limit == 4
        return [
            {"aid": "BTC", "pc": "USD", "qc": "BTC", "p": "100", "q": "1", "tdt": "2026-03-20T03:00:01Z"},
            {"aid": "BTC", "pc": "USD", "qc": "BTC", "p": "-1", "q": "1", "tdt": "2026-03-20T03:00:02Z"},
            {"aid": "BTC", "pc": "USD", "qc": "BTC", "p": "bad", "q": "1", "tdt": "2026-03-20T03:00:03Z"},
            {"aid": "ETH", "pc": "USD", "qc": "ETH", "p": "101", "q": "1", "tdt": "2026-03-20T03:00:04Z"},
        ]

    rows = fetch_trade_updates("BTC-USD", limit=4, fetcher=_fake_trades)
    assert len(rows) == 1
    assert rows[0].price == 100.0
    assert rows[0].size == 1.0


def test_feature_engine_incremental_cache_hit_uses_version_key():
    store = MarketDataStateStore()
    calls = {"n": 0}

    def _rsi(prices, period=14):
        calls["n"] += 1
        return 55.0

    prices = [100.0 + (i * 0.1) for i in range(150)]
    weights = [10.0 for _ in prices]
    first = resolve_indicator_features(
        store=store,
        symbol="BTC-USD",
        timeframe="1m",
        history_source="sqlite_candles",
        history_version=1,
        latest_open_time=9_000_000,
        prices=prices,
        weights=weights,
        atr_floor=0.0,
        rsi_fn=_rsi,
    )
    second = resolve_indicator_features(
        store=store,
        symbol="BTC-USD",
        timeframe="1m",
        history_source="sqlite_candles",
        history_version=1,
        latest_open_time=9_000_000,
        prices=prices,
        weights=weights,
        atr_floor=0.0,
        rsi_fn=_rsi,
    )
    third = resolve_indicator_features(
        store=store,
        symbol="BTC-USD",
        timeframe="1m",
        history_source="sqlite_candles",
        history_version=1,
        latest_open_time=9_060_000,
        prices=prices,
        weights=weights,
        atr_floor=0.0,
        rsi_fn=_rsi,
    )

    assert first.cache_hit is False
    assert second.cache_hit is True
    assert third.cache_hit is False
    assert calls["n"] == 2


def test_decision_context_blocks_when_strategy_gate_blocks():
    context = build_decision_context(
        {
            "symbol": "BTC-USD",
            "price": 100.0,
            "data_quality_status": "GOOD",
            "snapshot_version": 2,
            "strategy_eval_gate": {
                "allowed": False,
                "blocked_reason": "market_snapshot_stale",
            },
        },
        {},
    )
    assert context.allowed is False
    assert context.blocked_reason == "market_snapshot_stale"
    assert context.strategy_input is None
