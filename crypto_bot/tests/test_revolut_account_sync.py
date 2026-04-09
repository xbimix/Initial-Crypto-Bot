from __future__ import annotations

from api import revolut_account_sync


def _reset_quote_cache_state():
    revolut_account_sync._MID_PRICE_CACHE.clear()
    for key in list(revolut_account_sync._QUOTE_CACHE_STATS.keys()):
        revolut_account_sync._QUOTE_CACHE_STATS[key] = 0


def test_sync_account_snapshot_parses_balances(monkeypatch, tmp_path):
    _reset_quote_cache_state()
    snapshot_path = tmp_path / "revolut_account_snapshot.json"
    monkeypatch.setattr(revolut_account_sync, "ACCOUNT_SNAPSHOT_PATH", snapshot_path)
    monkeypatch.setattr(
        revolut_account_sync,
        "get_balances",
        lambda: {
            "data": [
                {"asset": "USD", "available": "100.5", "locked": "0"},
                {"asset": "BTC", "available": "0.25", "locked": "0.05"},
            ]
        },
    )
    monkeypatch.setattr(
        revolut_account_sync,
        "_estimate_symbol_mid_price",
        lambda symbol: 68000.0 if symbol == "BTC-USD" else None,
    )

    payload = revolut_account_sync.sync_account_snapshot()
    assert payload["sync_status"] == "ok"
    assert payload["asset_count"] == 2
    assert "quote_cache" in payload
    btc = next(row for row in payload["assets"] if row["asset"] == "BTC")
    assert btc["estimated_quote_value"] == 20400.0
    usd = next(row for row in payload["assets"] if row["asset"] == "USD")
    assert usd["estimated_quote_value"] == 100.5


def test_sync_account_snapshot_handles_api_error(monkeypatch, tmp_path):
    _reset_quote_cache_state()
    snapshot_path = tmp_path / "revolut_account_snapshot.json"
    monkeypatch.setattr(revolut_account_sync, "ACCOUNT_SNAPSHOT_PATH", snapshot_path)
    monkeypatch.setattr(
        revolut_account_sync,
        "get_balances",
        lambda: (_ for _ in ()).throw(RuntimeError("bad auth")),
    )

    payload = revolut_account_sync.sync_account_snapshot()
    assert payload["sync_status"] == "error"
    assert "bad auth" in payload["sync_error"]


def test_sync_account_snapshot_preserves_last_good_snapshot_on_error(monkeypatch, tmp_path):
    _reset_quote_cache_state()
    snapshot_path = tmp_path / "revolut_account_snapshot.json"
    monkeypatch.setattr(revolut_account_sync, "ACCOUNT_SNAPSHOT_PATH", snapshot_path)

    first_payload = {
        "data": [
            {"asset": "USD", "available": "250.0", "locked": "0"},
        ]
    }
    monkeypatch.setattr(revolut_account_sync, "get_balances", lambda: first_payload)
    ok = revolut_account_sync.sync_account_snapshot()
    assert ok["sync_status"] == "ok"
    assert ok["asset_count"] == 1

    monkeypatch.setattr(
        revolut_account_sync,
        "get_balances",
        lambda: (_ for _ in ()).throw(RuntimeError("upstream 409")),
    )
    err = revolut_account_sync.sync_account_snapshot()
    assert err["sync_status"] == "error"
    assert "upstream 409" in err["sync_error"]
    assert err["asset_count"] == 1
    assert err["assets"][0]["asset"] == "USD"
    assert err["estimated_total_quote_value"] == 250.0
    assert err["fallback_from_last_good_snapshot"] is True


def test_estimate_symbol_mid_price_uses_cache_within_ttl(monkeypatch):
    _reset_quote_cache_state()
    calls = {"n": 0}
    monkeypatch.setattr(revolut_account_sync, "_MID_PRICE_CACHE", {})
    monkeypatch.setattr(revolut_account_sync, "_cache_ttl_seconds", lambda: 180.0)
    monkeypatch.setattr(revolut_account_sync.time, "time", lambda: 1_000.0)

    def _book(symbol):
        calls["n"] += 1
        return {
            "data": {
                "bids": [{"p": "99.0"}],
                "asks": [{"p": "101.0"}],
            }
        }

    monkeypatch.setattr(revolut_account_sync, "get_order_book", _book)

    first = revolut_account_sync._estimate_symbol_mid_price("BTC-USD")
    second = revolut_account_sync._estimate_symbol_mid_price("BTC-USD")
    assert first == 100.0
    assert second == 100.0
    assert calls["n"] == 1
    telemetry = revolut_account_sync.quote_cache_telemetry()
    assert telemetry["hits"] >= 1
    assert telemetry["misses"] >= 1


def test_estimate_symbol_mid_price_cache_expires(monkeypatch):
    _reset_quote_cache_state()
    calls = {"n": 0}
    now = {"t": 1_000.0}
    monkeypatch.setattr(revolut_account_sync, "_MID_PRICE_CACHE", {})
    monkeypatch.setattr(revolut_account_sync, "_cache_ttl_seconds", lambda: 30.0)
    monkeypatch.setattr(revolut_account_sync.time, "time", lambda: now["t"])

    def _book(symbol):
        calls["n"] += 1
        return {
            "data": {
                "bids": [{"p": "49.0"}],
                "asks": [{"p": "51.0"}],
            }
        }

    monkeypatch.setattr(revolut_account_sync, "get_order_book", _book)

    first = revolut_account_sync._estimate_symbol_mid_price("ETH-USD")
    now["t"] = 1_031.0
    second = revolut_account_sync._estimate_symbol_mid_price("ETH-USD")
    assert first == 50.0
    assert second == 50.0
    assert calls["n"] == 2
    telemetry = revolut_account_sync.quote_cache_telemetry()
    assert telemetry["expired"] >= 1


def test_estimate_symbol_mid_price_cache_enforces_max_entries(monkeypatch):
    _reset_quote_cache_state()
    now = {"t": 1_000.0}
    monkeypatch.setattr(revolut_account_sync.time, "time", lambda: now["t"])
    monkeypatch.setattr(revolut_account_sync, "_cache_ttl_seconds", lambda: 1_000.0)
    monkeypatch.setattr(revolut_account_sync, "_cache_entry_limit", lambda: 2)

    books = {
        "BTC-USD": {"data": {"bids": [{"p": "99.0"}], "asks": [{"p": "101.0"}]}},
        "ETH-USD": {"data": {"bids": [{"p": "49.0"}], "asks": [{"p": "51.0"}]}},
        "SOL-USD": {"data": {"bids": [{"p": "9.0"}], "asks": [{"p": "11.0"}]}},
    }

    monkeypatch.setattr(revolut_account_sync, "get_order_book", lambda symbol: books[symbol])

    assert revolut_account_sync._estimate_symbol_mid_price("BTC-USD") == 100.0
    now["t"] += 1
    assert revolut_account_sync._estimate_symbol_mid_price("ETH-USD") == 50.0
    now["t"] += 1
    assert revolut_account_sync._estimate_symbol_mid_price("SOL-USD") == 10.0

    telemetry = revolut_account_sync.quote_cache_telemetry()
    assert telemetry["cache_size"] == 2
    assert telemetry["evicted_overflow"] >= 1


def test_quote_cache_stale_eviction_updates_telemetry(monkeypatch):
    _reset_quote_cache_state()
    now = {"t": 1_000.0}
    monkeypatch.setattr(revolut_account_sync.time, "time", lambda: now["t"])
    monkeypatch.setattr(revolut_account_sync, "_cache_ttl_seconds", lambda: 10.0)
    monkeypatch.setattr(revolut_account_sync, "_cache_entry_limit", lambda: 256)

    books = {
        "BTC-USD": {"data": {"bids": [{"p": "99.0"}], "asks": [{"p": "101.0"}]}},
        "ETH-USD": {"data": {"bids": [{"p": "49.0"}], "asks": [{"p": "51.0"}]}},
    }
    monkeypatch.setattr(revolut_account_sync, "get_order_book", lambda symbol: books[symbol])

    assert revolut_account_sync._estimate_symbol_mid_price("BTC-USD") == 100.0
    now["t"] = 1_030.0
    assert revolut_account_sync._estimate_symbol_mid_price("ETH-USD") == 50.0

    telemetry = revolut_account_sync.quote_cache_telemetry()
    assert telemetry["evicted_stale"] >= 1
    assert telemetry["cleanup_runs"] >= 1
