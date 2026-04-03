from __future__ import annotations

from tools import regime_confidence_recalibration_report as report


def test_build_closed_parts_and_regime_stats_use_buy_regime_metadata():
    rows = [
        {
            "time": 1000.0,
            "symbol": "BTC-USD",
            "side": "BUY",
            "price": 100.0,
            "size": 1.0,
            "entry_regime": "trend_up",
            "effective_route": "trend_pullback",
        },
        {
            "time": 1600.0,
            "symbol": "BTC-USD",
            "side": "SELL",
            "price": 105.0,
            "size": 1.0,
            "reason": "exit_signal",
        },
    ]
    parts = report._build_closed_parts(rows, start_ts=900.0, end_ts=2000.0)
    assert len(parts) == 1
    assert parts[0]["regime"] == "trend_up"
    assert parts[0]["route"] == "trend_pullback"

    stats = report._regime_stats(parts)
    assert stats["trend_up"]["closed_parts"] == 1
    assert stats["trend_up"]["expectancy_usd"] == 5.0
    assert stats["trend_up"]["win_rate_pct"] == 100.0
    assert stats["trend_up"]["route_mix"]["trend_pullback"] == 1


def test_confidence_adjustments_tighten_and_relax_by_outcomes():
    recent = {
        "choppy": {"closed_parts": 8, "expectancy_usd": -0.8, "win_rate_pct": 30.0},
        "trend_up": {"closed_parts": 8, "expectancy_usd": 1.2, "win_rate_pct": 75.0},
    }
    prior = {
        "choppy": {"closed_parts": 8, "expectancy_usd": -0.3, "win_rate_pct": 40.0},
        "trend_up": {"closed_parts": 8, "expectancy_usd": 0.9, "win_rate_pct": 65.0},
    }
    guidance = report._confidence_adjustments(
        recent_stats=recent,
        prior_stats=prior,
        min_closed_parts=6,
    )
    suggestions = {row["regime"]: row for row in guidance["suggestions"]}
    assert suggestions["choppy"]["action"] == "tighten"
    assert suggestions["choppy"]["confidence_delta"] == 5
    assert suggestions["trend_up"]["action"] == "relax"
    assert suggestions["trend_up"]["confidence_delta"] == -3
    patch = guidance["config_patch_preview"]["strategy_defaults"]["router"]["regime_confidence_adjustments"]
    assert patch["choppy"] == 5
    assert patch["trend_up"] == -3
