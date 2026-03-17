from __future__ import annotations

from api import revolut_account_sync


def test_sync_account_snapshot_parses_balances(monkeypatch, tmp_path):
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
    btc = next(row for row in payload["assets"] if row["asset"] == "BTC")
    assert btc["estimated_quote_value"] == 20400.0
    usd = next(row for row in payload["assets"] if row["asset"] == "USD")
    assert usd["estimated_quote_value"] == 100.5


def test_sync_account_snapshot_handles_api_error(monkeypatch, tmp_path):
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
