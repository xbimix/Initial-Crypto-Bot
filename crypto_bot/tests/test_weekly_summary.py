from __future__ import annotations

import json
from pathlib import Path

from reporting import weekly_summary


def _write_json(path: Path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2), encoding="utf-8")


def test_weekly_summary_build_and_write(tmp_path: Path, monkeypatch):
    reports_dir = tmp_path / "reports"
    monkeypatch.setattr(weekly_summary, "REPORTS_DIR", reports_dir)

    _write_json(
        reports_dir / "daily_summary_2026-03-12.json",
        {
            "day_utc": "2026-03-12",
            "summary": {
                "realized_pnl_usd": 12.5,
                "unrealized_pnl_usd": -3.0,
                "net_paper_pnl_usd": 9.5,
                "max_open_drawdown_pct": -4.2,
                "max_drawdown_during_trade_pct": -5.5,
                "max_drawdown_during_trade_symbol": "ADA-USD",
                "stale_losing_review_count": 2,
                "symbols_flagged_high_opportunity_count": 1,
            },
            "run_quality": {
                "crash_count": 0,
                "restart_count": 2,
                "data_gap_incidents": 1,
                "stale_data_blocks": 120,
            },
            "advisory": {
                "volatility_opportunity_radar": {
                    "symbols": [
                        {
                            "symbol": "ADA-USD",
                            "score": 78.2,
                            "label": "HIGH",
                            "insufficient_data": False,
                        },
                        {
                            "symbol": "BTC-USD",
                            "score": 52.0,
                            "label": "MEDIUM",
                            "insufficient_data": False,
                        },
                    ]
                },
                "regime_route_effectiveness": {
                    "total_closed_trades": 3,
                    "best_route_by_avg_pnl": "mean_reversion",
                    "best_route_avg_pnl_usd": 4.2,
                    "routes": {
                        "mean_reversion": {
                            "closed_trades": 2,
                            "win_rate_pct": 50.0,
                            "avg_realized_pnl_usd": 4.2,
                            "avg_max_drawdown_pct": -1.2,
                        },
                        "trend_pullback": {
                            "closed_trades": 1,
                            "win_rate_pct": 100.0,
                            "avg_realized_pnl_usd": 6.0,
                            "avg_max_drawdown_pct": -0.5,
                        },
                    },
                },
            },
            "trade_reasons": {
                "blocked_reasons": {"spread_too_wide": 2},
            },
        },
    )
    _write_json(
        reports_dir / "daily_summary_2026-03-13.json",
        {
            "day_utc": "2026-03-13",
            "summary": {
                "realized_pnl_usd": -5.0,
                "unrealized_pnl_usd": 8.0,
                "net_paper_pnl_usd": 3.0,
                "max_open_drawdown_pct": -6.0,
                "max_drawdown_during_trade_pct": -8.25,
                "max_drawdown_during_trade_symbol": "BTC-USD",
                "stale_losing_review_count": 1,
                "symbols_flagged_high_opportunity_count": 2,
            },
            "run_quality": {
                "crash_count": 1,
                "restart_count": 6,
                "data_gap_incidents": 0,
                "stale_data_blocks": 700,
            },
            "advisory": {
                "volatility_opportunity_radar": {
                    "symbols": [
                        {
                            "symbol": "BTC-USD",
                            "score": 82.5,
                            "label": "HIGH",
                            "insufficient_data": False,
                        },
                        {
                            "symbol": "ADA-USD",
                            "score": 71.0,
                            "label": "HIGH",
                            "insufficient_data": False,
                        },
                    ]
                },
                "regime_route_effectiveness": {
                    "total_closed_trades": 2,
                    "best_route_by_avg_pnl": "breakout_momentum",
                    "best_route_avg_pnl_usd": 5.5,
                    "routes": {
                        "breakout_momentum": {
                            "closed_trades": 1,
                            "win_rate_pct": 100.0,
                            "avg_realized_pnl_usd": 5.5,
                            "avg_max_drawdown_pct": -0.3,
                        },
                        "mean_reversion": {
                            "closed_trades": 1,
                            "win_rate_pct": 0.0,
                            "avg_realized_pnl_usd": -2.5,
                            "avg_max_drawdown_pct": -1.8,
                        },
                    },
                },
            },
            "trade_reasons": {
                "blocked_reasons": {"spread_too_wide": 1, "warming_up_history": 3},
            },
        },
    )

    report = weekly_summary.build_weekly_summary("2026-03-13", day_count=2)
    assert "generated_at" in report
    assert report["generated_at"] == report["generated_at_utc"]
    assert report["coverage"]["window_type"] == "weekly"
    assert report["coverage"]["requested_day_count"] == 2
    assert report["coverage"]["available_day_count"] == 2
    assert report["freshness"]["indicator"] in {"fresh", "stale"}
    assert isinstance(report["freshness"]["is_fresh"], bool)
    assert report["window"]["available_day_count"] == 2
    assert report["summary"]["realized_pnl_total_usd"] == 7.5
    assert report["summary"]["latest_unrealized_pnl_usd"] == 8.0
    assert report["summary"]["latest_stale_losing_review_count"] == 1
    assert report["summary"]["stale_losing_review_count_total"] == 3
    assert report["summary"]["latest_max_drawdown_during_trade_pct"] == -8.25
    assert report["summary"]["latest_max_drawdown_during_trade_symbol"] == "BTC-USD"
    assert report["summary"]["latest_rotation_rising_count"] == 0
    assert report["summary"]["latest_rotation_capital_trap_risk_count"] == 0
    assert report["summary"]["worst_max_drawdown_during_trade_pct"] == -8.25
    assert report["summary"]["restart_count_total"] == 8
    assert report["summary"]["crash_count_total"] == 1
    assert report["summary"]["latest_high_opportunity_symbol_count"] == 2
    assert report["summary"]["top_high_opportunity_symbols"] == ["ADA-USD", "BTC-USD"]
    assert report["summary"]["latest_best_regime_route_by_avg_pnl"] == "breakout_momentum"
    assert report["summary"]["weekly_best_regime_route_by_avg_pnl"] == "trend_pullback"
    assert report["summary"]["weekly_best_regime_route_avg_pnl_usd"] == 6.0
    assert report["blocked_reasons_top"]["spread_too_wide"] == 3
    assert report["blocked_reasons_top"]["warming_up_history"] == 3
    assert report["volatility_opportunity"]["high_signal_frequency_by_symbol"]["ADA-USD"] == 2
    assert report["volatility_opportunity"]["high_signal_frequency_by_symbol"]["BTC-USD"] == 1
    assert report["volatility_opportunity"]["average_opportunity_score_by_symbol"]["BTC-USD"] == 67.25
    assert report["regime_route_effectiveness"]["routes"]["mean_reversion"]["closed_trades"] == 3
    assert report["regime_route_effectiveness"]["routes"]["trend_pullback"]["avg_realized_pnl_usd"] == 6.0
    assert report["regime_route_effectiveness"]["routes"]["breakout_momentum"]["win_rate_pct"] == 100.0
    assert report["anomaly_notes"]

    output_path = weekly_summary.write_weekly_summary(report)
    assert output_path.exists()
    assert (reports_dir / "weekly_summary_latest.json").exists()
