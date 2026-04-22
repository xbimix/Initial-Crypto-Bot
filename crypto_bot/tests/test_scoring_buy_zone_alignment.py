from __future__ import annotations

from strategy import diagnostics
from strategy.scoring import score_indicators


def test_mr_scoring_respects_configured_range_cap_override():
    indicators = {
        "rsi": 30.0,
        "momentum": 0.1,
        "structure": 1.0,
        "mr_score_max_range_pos": 0.50,
    }
    score = score_indicators("range", indicators, range_pos=0.40)
    assert score > 0.0


def test_mr_scoring_keeps_legacy_cap_when_override_missing():
    indicators = {
        "rsi": 30.0,
        "momentum": 0.1,
        "structure": 1.0,
    }
    score = score_indicators("range", indicators, range_pos=0.40)
    assert score == 0.0


def test_compute_buy_diagnostics_passes_buy_zone_high_to_mr_scoring(monkeypatch):
    monkeypatch.setattr(diagnostics, "detect_regime", lambda *_args, **_kwargs: "range")

    parse_numeric = lambda value, fallback=None: float(value) if value is not None else fallback
    snapshot = {"rsi": 30.0}

    _, score_wide, _, _ = diagnostics.compute_buy_diagnostics(
        snapshot=snapshot,
        price=90.0,
        momentum=0.1,
        high_24h=100.0,
        low_24h=80.0,
        atr=0.01,
        z_score=-2.0,
        regime_cfg={"preferred_buy_zone": [-0.1, 0.5]},
        parse_numeric=parse_numeric,
    )
    _, score_tight, _, _ = diagnostics.compute_buy_diagnostics(
        snapshot=snapshot,
        price=90.0,
        momentum=0.1,
        high_24h=100.0,
        low_24h=80.0,
        atr=0.01,
        z_score=-2.0,
        regime_cfg={"preferred_buy_zone": [-0.1, 0.3]},
        parse_numeric=parse_numeric,
    )

    assert score_wide > 0.0
    assert score_tight == 0.0
