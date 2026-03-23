from __future__ import annotations

from strategy import diagnostics


def _parse_numeric(value, fallback=None):
    try:
        return float(value)
    except (TypeError, ValueError):
        return fallback


def _snapshot(recent_prices):
    return {
        "symbol": "BTC-USD",
        "rsi": 50.0,
        "recent_prices": recent_prices,
    }


def test_structure_recompute_only_when_recent_prices_change(monkeypatch):
    diagnostics._structure_cache.clear()
    calls = {"count": 0}

    def _fake_sr(prices, window):
        calls["count"] += 1
        return min(prices), max(prices)

    monkeypatch.setattr(diagnostics, "calculate_support_resistance", _fake_sr)

    prices = [100 + (idx * 0.1) for idx in range(20)]
    payload = dict(
        price=101.0,
        momentum=0.1,
        high_24h=110.0,
        low_24h=90.0,
        atr=0.4,
        z_score=0.2,
        regime_cfg={},
        parse_numeric=_parse_numeric,
    )

    diagnostics.compute_buy_diagnostics(snapshot=_snapshot(prices), **payload)
    diagnostics.compute_buy_diagnostics(snapshot=_snapshot(prices), **payload)
    assert calls["count"] == 1

    changed = prices + [prices[-1] + 0.5]
    diagnostics.compute_buy_diagnostics(snapshot=_snapshot(changed), **payload)
    assert calls["count"] == 2
