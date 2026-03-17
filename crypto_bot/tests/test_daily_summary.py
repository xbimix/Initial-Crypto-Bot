from __future__ import annotations

import json
from pathlib import Path

from reporting import daily_summary


def _write_json(path: Path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2), encoding="utf-8")


def test_daily_summary_build_and_write(tmp_path, monkeypatch):
    state_dir = tmp_path / "state"
    reports_dir = state_dir / "reports"
    config_path = state_dir / "config.json"
    paper_state_path = state_dir / "paper_state.json"
    strategy_state_path = state_dir / "strategy_state.json"
    trades_path = state_dir / "trades.json"
    runtime_events_path = state_dir / "runtime_events.jsonl"
    bot_log_path = state_dir / "bot.log"

    _write_json(
        config_path,
        {
            "risk": {
                "stale_losing_review_age_hours": 24,
                "stale_losing_review_unrealized_pnl_pct": -8,
            }
        },
    )
    _write_json(
        paper_state_path,
        {
            "balance": 10000,
            "positions": {
                "ADA-USD": {
                    "price": 10.0,
                    "size": 1.0,
                    "entry_time": 1_710_373_200.0,
                    "reason": "carry",
                }
            },
        },
    )
    _write_json(strategy_state_path, {})
    _write_json(
        trades_path,
        [
                {
                "time": 1_710_158_400.0,  # 2024-03-11T12:00:00Z
                    "symbol": "BTC-USD",
                    "side": "BUY",
                    "price": 100.0,
                    "size": 1.0,
                    "reason": "entry_signal",
                },
                {
                "time": 1_710_162_000.0,  # 2024-03-11T13:00:00Z
                    "symbol": "BTC-USD",
                    "side": "SELL",
                    "price": 105.0,
                    "size": 1.0,
                "pnl": 5.0,
                "reason": "exit_signal",
            },
        ],
    )
    runtime_events_path.write_text(
        json.dumps(
            {
                "day_utc": "2024-03-11",
                "event_type": "health_check",
                "ok": False,
            }
        )
        + "\n",
        encoding="utf-8",
    )
    bot_log_path.write_text(
        "\n".join(
            [
                "2024-03-11 00:00:00,000 | INFO | RevBot starting (paper mode default)",
                "2024-03-11 12:30:00,000 | INFO | SNAPSHOT ADA-USD | price=9.00000 bid=8.99000 ask=9.01000 spread_bps=20.00 mom_norm=0.100 rsi=50.00 atr_raw=0.02000 vwap=9.50000 points=30 quality=ok 24h_low=8.50000 24h_high=10.50000",
                "2024-03-11 12:31:00,000 | INFO | SNAPSHOT BTC-USD | price=105.00000 bid=104.90000 ask=105.10000 spread_bps=190.00 mom_norm=0.200 rsi=52.00 atr_raw=0.03000 vwap=104.00000 points=40 quality=spread_too_wide 24h_low=101.00000 24h_high=110.00000",
                "2024-03-11 12:32:00,000 | INFO | BUY blocked for BTC-USD (spread_too_wide)",
                "2024-03-11 12:33:00,000 | INFO | BTC-USD -> HOLD | reason=warming_up_history",
                "2024-03-11 12:34:00,000 | ERROR | Main loop error: boom",
            ]
        ),
        encoding="utf-8",
    )

    monkeypatch.setattr(daily_summary, "STATE_DIR", state_dir)
    monkeypatch.setattr(daily_summary, "CONFIG_PATH", config_path)
    monkeypatch.setattr(daily_summary, "PAPER_STATE_PATH", paper_state_path)
    monkeypatch.setattr(daily_summary, "STRATEGY_STATE_PATH", strategy_state_path)
    monkeypatch.setattr(daily_summary, "TRADES_PATH", trades_path)
    monkeypatch.setattr(daily_summary, "REPORTS_DIR", reports_dir)
    monkeypatch.setattr(daily_summary, "RUNTIME_EVENTS_PATH", runtime_events_path)

    report = daily_summary.build_daily_summary("2024-03-11")

    assert "generated_at" in report
    assert report["generated_at"] == report["generated_at_utc"]
    assert report["coverage"]["window_type"] == "daily"
    assert report["coverage"]["day_utc"] == "2024-03-11"
    assert report["coverage"]["window_days"] == 1
    assert report["freshness"]["indicator"] in {"fresh", "stale"}
    assert isinstance(report["freshness"]["is_fresh"], bool)
    assert report["summary"]["total_buys"] == 1
    assert report["summary"]["total_sells"] == 1
    assert report["summary"]["realized_pnl_usd"] == 5.0
    assert report["summary"]["unrealized_pnl_usd"] == -1.0
    assert report["summary"]["net_paper_pnl_usd"] == 4.0
    assert report["summary"]["open_positions_count"] == 1
    assert report["summary"]["stale_losing_review_count"] == 1
    assert report["summary"]["max_drawdown_during_trade_pct"] == -10.0
    assert report["summary"]["max_drawdown_during_trade_symbol"] == "ADA-USD"
    assert report["summary"]["win_rate_pct"] == 100.0
    assert report["summary"]["avg_holding_seconds"] == 3600.0
    assert report["advisory"]["max_drawdown_during_trade"]["tracked_positions_count"] == 1
    assert report["advisory"]["max_drawdown_during_trade"]["worst_max_drawdown_pct"] == -10.0
    assert report["advisory"]["max_drawdown_during_trade"]["worst_symbol"] == "ADA-USD"
    assert report["advisory"]["max_drawdown_during_trade"]["positions"][0]["symbol"] == "ADA-USD"
    assert report["advisory"]["stale_losing_review"]["threshold_age_hours"] == 24.0
    assert report["advisory"]["stale_losing_review"]["threshold_unrealized_pnl_pct"] == -8.0
    assert report["advisory"]["stale_losing_review"]["flagged_count"] == 1
    assert report["advisory"]["stale_losing_review"]["flagged_symbols"] == ["ADA-USD"]
    assert "rolling_symbol_rotation" in report["advisory"]
    rotation = report["advisory"]["rolling_symbol_rotation"]
    assert rotation["short_window"]["days"] == 7
    assert rotation["medium_window"]["max_closed_trades"] == 30
    assert isinstance(rotation["symbols"], list)
    assert "Rising" in rotation["status_counts"]
    assert "top_volatility_opportunity_symbols" in report["summary"]
    assert "highest_opportunity_score" in report["summary"]
    assert "symbols_flagged_high_opportunity_count" in report["summary"]
    assert report["summary"]["symbols_flagged_high_opportunity_count"] == 0
    assert report["summary"]["highest_opportunity_score"] is None
    assert report["summary"]["regime_route_closed_trades"] == 1
    assert report["summary"]["best_regime_route_by_avg_pnl"] == "mean_reversion"
    assert "volatility_opportunity_radar" in report["advisory"]
    radar = report["advisory"]["volatility_opportunity_radar"]
    assert isinstance(radar["symbols"], list)
    assert radar["high_opportunity_symbol_count"] == 0
    assert "regime_route_effectiveness" in report["advisory"]
    route_effectiveness = report["advisory"]["regime_route_effectiveness"]
    assert route_effectiveness["total_closed_trades"] == 1
    assert route_effectiveness["best_route_by_avg_pnl"] == "mean_reversion"
    assert route_effectiveness["routes"]["mean_reversion"]["closed_trades"] == 1
    assert report["trade_reasons"]["entry_reasons"]["entry_signal"] == 1
    assert report["trade_reasons"]["exit_reasons"]["exit_signal"] == 1
    assert report["trade_reasons"]["blocked_reasons"]["spread_too_wide"] == 1
    assert report["run_quality"]["restart_count"] == 1
    assert report["run_quality"]["crash_count"] == 1
    assert report["run_quality"]["stale_data_blocks"] == 2
    assert report["run_quality"]["health_check_issues"] == 1
    assert report["run_quality"]["data_gap_incidents"] == 1

    out_path = daily_summary.write_daily_summary(report)
    assert out_path.exists()
    latest_path = reports_dir / "daily_summary_latest.json"
    assert latest_path.exists()
    latest = json.loads(latest_path.read_text(encoding="utf-8"))
    assert latest["day_utc"] == "2024-03-11"
