from __future__ import annotations

from strategy.regime_engine_v2 import evaluate_regime_v2


def _snapshot(**overrides):
    base = {
        "symbol": "TEST-USD",
        "trade_count": 30,
        "spread_bps": 25.0,
        "recent_prices": [100 + (idx * 0.08) for idx in range(300)],
        "snapshot_ts_epoch": 1_730_000_000.0,
        "sampling_minutes": 5.0,
    }
    base.update(overrides)
    return base


def test_regime_v2_returns_expected_shape():
    result = evaluate_regime_v2(snapshot=_snapshot(), now_epoch=1_730_000_050.0, cfg={})
    assert "suggestedRegime" in result
    assert "suggestedRegimeLabel" in result
    assert "regimeTier" in result
    assert "confidenceScore" in result
    assert "stabilityScore" in result
    assert "persistenceScore" in result
    assert "timeframeSummary" in result
    assert "primaryScores" in result
    assert "qualityAnalytics" in result
    assert "volatilityAnalytics" in result
    assert "confidenceAnalytics" in result
    assert isinstance(result["timeframeSummary"], list)
    assert result["detectionSource"] == "regime_v2_runtime"


def test_regime_v2_degrades_when_history_is_shallow():
    result = evaluate_regime_v2(
        snapshot=_snapshot(recent_prices=[100.0, 100.1, 99.9]),
        now_epoch=1_730_000_050.0,
        cfg={},
    )
    assert result["suggestedRegime"] == "MIXED_OR_UNCLEAR"
    assert result["insufficientData"] is True
    assert result["dataQuality"]["status"] in {"INSUFFICIENT", "UNSUPPORTED_WINDOW"}


def test_regime_v2_marks_stale_data_quality():
    result = evaluate_regime_v2(
        snapshot=_snapshot(snapshot_ts_epoch=1_729_990_000.0),
        now_epoch=1_730_000_050.0,
        cfg={"strategy_defaults": {"router": {"auto_max_regime_age_seconds": 120}}},
    )
    assert result["dataQuality"]["status"] == "STALE"
    assert result["suggestedRegime"] == "MIXED_OR_UNCLEAR"
