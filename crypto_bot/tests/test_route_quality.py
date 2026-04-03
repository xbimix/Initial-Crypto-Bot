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


def test_route_quality_prefers_explicit_effective_route_over_reason(tmp_path: Path):
    state_dir = tmp_path / "state"
    state_dir.mkdir(parents=True, exist_ok=True)
    now = 1_000_000.0
    write_json_file(
        state_dir / "trades.json",
        [
            {
                "time": now - 1200,
                "symbol": "AAA-USD",
                "side": "SELL",
                "reason": "trend_pullback_exit",
                "effective_route": "mean_reversion",
                "pnl": 0.7,
            },
        ],
    )
    write_json_file(state_dir / "strategy_state.json", {"last_effective_route": {"AAA-USD": "mean_reversion"}})
    write_json_file(state_dir / "config.json", {})

    report = build_route_quality_report(state_dir=state_dir, cfg={"token_regimes": {}}, now_epoch=now)
    assert "mean_reversion" in report["windows"]["30d"]
    assert "trend_pullback" not in report["windows"]["30d"]
    assert report["per_token_route_history"]["AAA-USD"]["route_counts"]["mean_reversion"] == 1


def test_route_quality_includes_buy_block_gate_summaries(tmp_path: Path):
    state_dir = tmp_path / "state"
    state_dir.mkdir(parents=True, exist_ok=True)
    now = 1_000_000.0
    write_json_file(state_dir / "trades.json", [])
    write_json_file(
        state_dir / "strategy_state.json",
        {
            "buy_block_counts_by_symbol": {
                "AAA-USD": {"insufficient_data": 3, "score_below_threshold": 1},
                "BBB-USD": {"insufficient_data": 2},
            },
            "buy_block_counts_by_symbol_route": {
                "AAA-USD": {
                    "mean_reversion": {"insufficient_data": 2},
                    "trend_pullback": {"score_below_threshold": 1},
                },
                "BBB-USD": {
                    "mean_reversion": {"insufficient_data": 2},
                },
            },
        },
    )
    write_json_file(state_dir / "config.json", {})

    report = build_route_quality_report(state_dir=state_dir, cfg={"token_regimes": {}}, now_epoch=now)
    assert report["buy_block_gate_summary"]["insufficient_data"] == 5
    assert report["buy_block_gate_summary"]["score_below_threshold"] == 1
    assert report["buy_block_gate_by_route_summary"]["mean_reversion"]["insufficient_data"] == 4
    assert report["buy_block_gate_by_route_summary"]["trend_pullback"]["score_below_threshold"] == 1
    assert report["buy_block_gate_by_symbol_route_summary"]["AAA-USD|mean_reversion"]["insufficient_data"] == 2
    gate_health = report["gate_health_summary"]
    assert gate_health["buy_block_total"] == 6
    assert gate_health["top_buy_block_reasons"][0]["name"] == "insufficient_data"
    assert gate_health["top_buy_block_reasons"][0]["count"] == 5


def test_route_quality_gate_health_summary_tracks_readiness_and_promotion(tmp_path: Path):
    state_dir = tmp_path / "state"
    state_dir.mkdir(parents=True, exist_ok=True)
    now = 1_000_000.0
    write_json_file(state_dir / "trades.json", [])
    write_json_file(
        state_dir / "strategy_state.json",
        {
            "last_route_readiness_state": {
                "AAA-USD": "ready",
                "BBB-USD": "blocked",
                "CCC-USD": "ready",
            },
            "last_route_timestamp_fresh": {
                "AAA-USD": True,
                "BBB-USD": False,
                "CCC-USD": True,
            },
            "last_failed_gates": {
                "BBB-USD": ["min_confidence", "data_quality"],
                "DDD-USD": ["min_confidence"],
            },
        },
    )
    write_json_file(state_dir / "config.json", {})

    cfg = {
        "token_regimes": {},
        "strategy_defaults": {
            "router": {
                "trend_min_closed_trades": 1,
                "trend_min_win_rate_pct": 50,
                "trend_min_expectancy_usd": 0.1,
                "breakout_min_closed_trades": 1,
                "breakout_min_win_rate_pct": 50,
                "breakout_min_expectancy_usd": 0.1,
            }
        },
    }
    report = build_route_quality_report(state_dir=state_dir, cfg=cfg, now_epoch=now)

    gate_health = report["gate_health_summary"]
    assert gate_health["readiness_total"] == 3
    assert gate_health["readiness_ready"] == 2
    assert gate_health["readiness_not_ready"] == 1
    assert gate_health["readiness_ready_rate_pct"] == 66.67
    assert gate_health["timestamp_fresh_total"] == 3
    assert gate_health["timestamp_fresh"] == 2
    assert gate_health["timestamp_stale_or_missing"] == 1
    assert gate_health["timestamp_fresh_rate_pct"] == 66.67
    assert gate_health["failed_gate_total"] == 3
    assert gate_health["top_failed_gates"][0]["name"] == "min_confidence"
    assert gate_health["top_failed_gates"][0]["count"] == 2
    assert "trend_pullback" in gate_health["blocked_routes"]
