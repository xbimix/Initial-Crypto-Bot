from __future__ import annotations

from api import revolut_universe


def test_build_universe_snapshot_ranks_rows(monkeypatch, tmp_path):
    snapshot_path = tmp_path / "revolut_universe_snapshot.json"
    monkeypatch.setattr(revolut_universe, "UNIVERSE_SNAPSHOT_PATH", snapshot_path)
    monkeypatch.setattr(
        revolut_universe,
        "_fetch_revolut_instruments",
        lambda: (
            [
                {"symbol": "BTC-USD", "status": "TRADING"},
                {"symbol": "ETH-USD", "status": "TRADING"},
            ],
            ["source=/pairs"],
        ),
    )

    snapshots = {
        "BTC-USD": {
            "symbol": "BTC-USD",
            "spread_bps": 18.0,
            "trade_count": 90,
            "atr_raw": 0.013,
            "data_quality_ok": True,
            "data_quality_reason": "ok",
            "low_24h": 62000.0,
            "high_24h": 68000.0,
            "price": 63000.0,
            "momentum_norm": -0.6,
        },
        "ETH-USD": {
            "symbol": "ETH-USD",
            "spread_bps": 95.0,
            "trade_count": 12,
            "atr_raw": 0.002,
            "data_quality_ok": False,
            "data_quality_reason": "spread_too_wide,warming_up_history",
            "low_24h": 1800.0,
            "high_24h": 2300.0,
            "price": 2250.0,
            "momentum_norm": 1.2,
        },
    }
    monkeypatch.setattr(
        revolut_universe,
        "fetch_market_snapshot",
        lambda symbol, cfg: snapshots.get(symbol),
    )
    monkeypatch.setattr(revolut_universe, "detect_regime", lambda snapshot, regime_cfg: "range")

    cfg = {
        "symbols": ["BTC-USD"],
        "volatility_filters": {"min_atr": 0.003},
        "universe": {"enriched_snapshot_limit": 2},
    }
    payload = revolut_universe.build_universe_snapshot(cfg)
    assert payload["sync_status"] == "ok"
    assert payload["summary"]["total_symbols"] == 2
    assert payload["summary"]["tracked_count"] == 1
    assert len(payload["rows"]) == 2
    assert payload["rows"][0]["symbol"] == "BTC-USD"
    assert payload["rows"][0]["eligible"] is True
    assert payload["rows"][1]["eligible"] is False
    assert "market_quality_degraded" in payload["rows"][1]["reasons"]


def test_get_universe_snapshot_uses_cache(monkeypatch):
    cached_payload = {"generated_at": 9999999999.0, "rows": [], "summary": {"total_symbols": 0}}
    monkeypatch.setattr(revolut_universe, "read_universe_snapshot", lambda default=None: cached_payload)
    called = {"build": 0}

    def fake_build(cfg):
        called["build"] += 1
        return {"generated_at": 1.0, "rows": [], "summary": {"total_symbols": 0}}

    monkeypatch.setattr(revolut_universe, "build_universe_snapshot", fake_build)
    payload = revolut_universe.get_universe_snapshot({"symbols": []}, force_refresh=False)
    assert payload is cached_payload
    assert called["build"] == 0


def test_build_universe_snapshot_uses_ticker_fallback_when_deep_snapshot_missing(
    monkeypatch,
    tmp_path,
):
    snapshot_path = tmp_path / "revolut_universe_snapshot.json"
    monkeypatch.setattr(revolut_universe, "UNIVERSE_SNAPSHOT_PATH", snapshot_path)
    monkeypatch.setattr(
        revolut_universe,
        "_fetch_revolut_instruments",
        lambda: (
            [
                {"symbol": "TON/USDC", "bid": "1.32", "ask": "1.33", "mid": "1.325"},
                {"symbol": "ETH/USD", "bid": "2300", "ask": "2302", "mid": "2301"},
            ],
            ["source=/tickers"],
        ),
    )
    monkeypatch.setattr(revolut_universe, "fetch_market_snapshot", lambda symbol, cfg: None)

    payload = revolut_universe.build_universe_snapshot({"symbols": []})
    assert payload["sync_status"] == "ok"
    assert payload["summary"]["total_symbols"] == 2
    assert payload["rows"][0]["symbol"] in {"ETH-USD", "TON-USDC"}
    assert payload["rows"][1]["symbol"] in {"ETH-USD", "TON-USDC"}
    assert payload["rows"][0]["overall_universe_score"] > 0
    assert payload["rows"][1]["overall_universe_score"] > 0
