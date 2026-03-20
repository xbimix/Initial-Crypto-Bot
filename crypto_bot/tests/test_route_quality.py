from __future__ import annotations

from pathlib import Path

from strategy.route_quality import build_route_quality_report
from utils.state_io import write_json_file


def test_route_quality_report_builds_and_promotes_when_thresholds_met(tmp_path: Path):
    state_dir = tmp_path / "state"
    state_dir.mkdir(parents=True, exist_ok=True)
    now = 1_000_000.0
    write_json_file(
        state_dir / "trades.json",
        [
            {
                "time": now - 3600,
                "symbol": "AAA-USD",
                "side": "SELL",
                "reason": "trend_pullback_exit",
                "pnl": 1.2,
            },
            {
                "time": now - 7200,
                "symbol": "BBB-USD",
                "side": "SELL",
                "reason": "breakout_momentum_exit",
                "pnl": 2.0,
            },
        ],
    )
    write_json_file(
        state_dir / "strategy_state.json",
        {
            "last_effective_route": {"AAA-USD": "trend_pullback"},
            "last_fallback_reason": {"CCC-USD": "mixed_or_unclear_regime"},
            "last_auto_fallback_reason": {"DDD-USD": "low_confidence"},
        },
    )
    write_json_file(state_dir / "config.json", {})

    cfg = {
        "token_regimes": {
            "AAA-USD": "AUTO",
            "BBB-USD": "TREND_PULLBACK",
        },
        "strategy_defaults": {
            "router": {
                "trend_min_closed_trades": 1,
                "trend_min_win_rate_pct": 1,
                "trend_min_expectancy_usd": 0,
                "breakout_min_closed_trades": 1,
                "breakout_min_win_rate_pct": 1,
                "breakout_min_expectancy_usd": 0,
            }
        }
    }
    report = build_route_quality_report(state_dir=state_dir, cfg=cfg, now_epoch=now)

    assert "windows" in report
    assert "30d" in report["windows"]
    assert report["current"]["effective_route_counts"]["trend_pullback"] == 1
    assert report["current"]["fallback_reason_counts"]["mixed_or_unclear_regime"] == 1
    assert report["promotion"]["promoted_routes"]["trend_pullback"] is True
    assert report["promotion"]["promoted_routes"]["breakout_momentum"] is True
    assert report["route_usage_summary"]["trend_pullback"] == 1
    assert report["fallback_reason_summary"]["mixed_or_unclear_regime"] == 1
    assert report["manual_vs_auto_comparison"]["symbol_counts"]["AUTO"] == 1
    assert report["manual_vs_auto_comparison"]["symbol_counts"]["MANUAL"] == 0
    assert report["per_token_route_history"]["AAA-USD"]["count"] == 1
    assert report["per_token_route_history"]["BBB-USD"]["route_counts"]["breakout_momentum"] == 1
