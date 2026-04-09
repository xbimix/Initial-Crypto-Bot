from __future__ import annotations

from data import market_data


def test_fetch_market_snapshot_emits_typed_failure_for_order_book_fetch_error(monkeypatch):
    events: list[tuple[str, dict]] = []

    def _raise_fetch_error(symbol, cfg=None, fetcher=None):
        raise RuntimeError("order book unavailable")

    monkeypatch.setattr(market_data, "fetch_order_book_update", _raise_fetch_error)
    monkeypatch.setattr(
        market_data,
        "append_replay_event",
        lambda event, payload, cfg=None: events.append((event, dict(payload))),
    )

    snapshot = market_data.fetch_market_snapshot("BTC-USD", cfg={"market_data": {}})
    assert snapshot is None
    assert events
    event, payload = events[-1]
    assert event == "market_snapshot_failure"
    assert payload.get("symbol") == "BTC-USD"
    assert payload.get("code") == "order_book_fetch_error"
    assert payload.get("stage") == "ingestion_order_book"


def test_fetch_market_snapshot_emits_typed_failure_for_empty_order_book(monkeypatch):
    events: list[tuple[str, dict]] = []

    monkeypatch.setattr(market_data, "fetch_order_book_update", lambda symbol, cfg=None, fetcher=None: None)
    monkeypatch.setattr(
        market_data,
        "append_replay_event",
        lambda event, payload, cfg=None: events.append((event, dict(payload))),
    )

    snapshot = market_data.fetch_market_snapshot("BTC-USD", cfg={"market_data": {}})
    assert snapshot is None
    assert events
    event, payload = events[-1]
    assert event == "market_snapshot_failure"
    assert payload.get("symbol") == "BTC-USD"
    assert payload.get("code") == "order_book_empty"
    assert payload.get("stage") == "ingestion_order_book"
