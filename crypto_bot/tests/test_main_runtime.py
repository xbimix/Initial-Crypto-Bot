from __future__ import annotations

import json
from pathlib import Path

import main as bot_main
from utils.state_io import write_json_file


def _seed_state_files(state_dir: Path):
    write_json_file(state_dir / "config.json", {"enabled": False, "symbols": []})
    write_json_file(state_dir / "paper_state.json", {"balance": 10000, "positions": {}})
    write_json_file(state_dir / "strategy_state.json", {})
    write_json_file(state_dir / "trades.json", [])


def test_startup_checks_ok(tmp_path: Path, monkeypatch):
    state_dir = tmp_path / "state"
    state_dir.mkdir(parents=True, exist_ok=True)
    _seed_state_files(state_dir)

    monkeypatch.setattr(bot_main, "STATE_DIR", state_dir)
    monkeypatch.setattr(bot_main, "DEFAULT_STATE_DIR", state_dir)
    monkeypatch.setattr(bot_main, "load_config", lambda: {"enabled": False})

    status = bot_main._run_startup_checks()
    assert status["ok"] is True
    names = {check["name"] for check in status["checks"]}
    assert "state_dir_exists" in names
    assert "state_dir_writable" in names
    assert "config_loadable" in names
    assert "state_integrity_report" in names


def test_startup_checks_fail_when_config_unloadable(tmp_path: Path, monkeypatch):
    state_dir = tmp_path / "state"
    state_dir.mkdir(parents=True, exist_ok=True)
    _seed_state_files(state_dir)

    monkeypatch.setattr(bot_main, "STATE_DIR", state_dir)
    monkeypatch.setattr(bot_main, "DEFAULT_STATE_DIR", state_dir)

    def _fail():
        raise RuntimeError("config boom")

    monkeypatch.setattr(bot_main, "load_config", _fail)

    status = bot_main._run_startup_checks()
    assert status["ok"] is False
    failed = [item for item in status["checks"] if item["name"] == "config_loadable"]
    assert failed
    assert failed[0]["ok"] is False


def test_startup_checks_fail_when_deployed_arming_contract_missing(tmp_path: Path, monkeypatch):
    state_dir = tmp_path / "state"
    state_dir.mkdir(parents=True, exist_ok=True)
    _seed_state_files(state_dir)

    monkeypatch.setattr(bot_main, "STATE_DIR", state_dir)
    monkeypatch.setattr(bot_main, "DEFAULT_STATE_DIR", state_dir)
    monkeypatch.setattr(bot_main, "DEPLOYMENT_MODE", True)
    monkeypatch.setattr(bot_main, "STRICT_MUTATING_AUTH", False)
    monkeypatch.setattr(bot_main, "ALLOW_DEPLOYED_MUTATIONS", False)
    monkeypatch.setattr(bot_main, "ALLOW_DEPLOYED_LIVE_ARMING", False)
    monkeypatch.setattr(
        bot_main,
        "load_config",
        lambda: {
            "enabled": False,
            "trading_enabled": False,
            "execution_mode": "live",
        },
    )

    status = bot_main._run_startup_checks()
    assert status["ok"] is False
    checks = {item["name"]: item for item in status["checks"]}
    assert checks["arming_contract_mutating"]["ok"] is False
    assert checks["arming_contract_live_arming"]["ok"] is False
    assert bot_main._has_critical_startup_failure(status) is True


def test_startup_checks_pass_when_deployed_arming_contract_configured(tmp_path: Path, monkeypatch):
    state_dir = tmp_path / "state"
    state_dir.mkdir(parents=True, exist_ok=True)
    _seed_state_files(state_dir)

    monkeypatch.setattr(bot_main, "STATE_DIR", state_dir)
    monkeypatch.setattr(bot_main, "DEFAULT_STATE_DIR", state_dir)
    monkeypatch.setattr(bot_main, "DEPLOYMENT_MODE", True)
    monkeypatch.setattr(bot_main, "STRICT_MUTATING_AUTH", True)
    monkeypatch.setattr(bot_main, "ALLOW_DEPLOYED_MUTATIONS", True)
    monkeypatch.setattr(bot_main, "ALLOW_DEPLOYED_LIVE_ARMING", True)
    monkeypatch.setenv("REVBOT_CONTROL_AUTH_TOKEN", "test-token")
    monkeypatch.setattr(
        bot_main,
        "load_config",
        lambda: {
            "enabled": False,
            "trading_enabled": False,
            "execution_mode": "live",
        },
    )

    status = bot_main._run_startup_checks()
    checks = {item["name"]: item for item in status["checks"]}
    assert checks["arming_contract_mutating"]["ok"] is True
    assert checks["arming_contract_live_arming"]["ok"] is True


def test_build_symbol_poll_intervals_prioritizes_open_and_top_symbols(tmp_path: Path, monkeypatch):
    state_dir = tmp_path / "state"
    state_dir.mkdir(parents=True, exist_ok=True)
    _seed_state_files(state_dir)
    write_json_file(
        state_dir / "strategy_state.json",
        {
            "last_score": {
                "AAA-USD": 90,
                "BBB-USD": 70,
                "CCC-USD": 50,
                "DDD-USD": 10,
            },
            "last_volatility": {
                "AAA-USD": 0.02,
                "BBB-USD": 0.01,
            },
        },
    )

    monkeypatch.setattr(bot_main, "STATE_DIR", state_dir)
    cfg = {
        "symbols": ["AAA-USD", "BBB-USD", "CCC-USD", "DDD-USD", "EEE-USD"],
        "market_data": {
            "fast_poll_seconds": 20,
            "mid_poll_seconds": 90,
            "slow_poll_seconds": 240,
            "top_opportunity_count": 2,
            "mid_tier_count": 1,
        },
    }
    scan_symbols = cfg["symbols"]
    open_symbols = ["EEE-USD"]

    intervals = bot_main._build_symbol_poll_intervals(cfg, scan_symbols, open_symbols)

    assert intervals["EEE-USD"] == 20
    assert intervals["AAA-USD"] == 20
    assert intervals["BBB-USD"] == 20
    assert intervals["CCC-USD"] == 90
    assert intervals["DDD-USD"] == 240


def test_select_symbols_for_cycle_honors_due_and_max_per_cycle():
    symbols = ["AAA-USD", "BBB-USD", "CCC-USD", "DDD-USD"]
    now = 1_000.0
    interval_by_symbol = {
        "AAA-USD": 20,
        "BBB-USD": 20,
        "CCC-USD": 90,
        "DDD-USD": 240,
    }
    last_polled_at = {
        "AAA-USD": 970.0,   # due
        "BBB-USD": 990.0,   # not due
        "CCC-USD": 800.0,   # due
        "DDD-USD": 750.0,   # due
    }

    selected = bot_main._select_symbols_for_cycle(
        symbols=symbols,
        now_epoch=now,
        last_polled_at=last_polled_at,
        interval_by_symbol=interval_by_symbol,
        max_symbols_per_cycle=2,
    )

    # Fast tier due symbol should be selected first, then oldest due among remaining.
    assert selected == ["AAA-USD", "CCC-USD"]
    assert last_polled_at["AAA-USD"] == now
    assert last_polled_at["CCC-USD"] == now


def test_sync_symbols_for_tick_uses_scan_scope_by_default():
    cfg = {"market_data": {}}
    selected = bot_main._sync_symbols_for_tick(
        cfg=cfg,
        scan_symbols=["AAA-USD", "BBB-USD"],
        cycle_symbols=["AAA-USD"],
        open_symbols=["CCC-USD"],
    )
    assert selected == ["AAA-USD", "BBB-USD"]


def test_sync_symbols_for_tick_can_use_cycle_scope():
    cfg = {"market_data": {"sync_symbol_scope": "cycle"}}
    selected = bot_main._sync_symbols_for_tick(
        cfg=cfg,
        scan_symbols=["AAA-USD", "BBB-USD"],
        cycle_symbols=["AAA-USD"],
        open_symbols=["CCC-USD"],
    )
    assert selected == ["AAA-USD"]


def test_sync_symbols_for_tick_can_append_stale_catchup_symbols():
    cfg = {
        "market_data": {
            "sync_symbol_scope": "cycle",
            "sync_stale_catchup_enabled": True,
            "sync_stale_catchup_max_symbols": 1,
        }
    }
    selected = bot_main._sync_symbols_for_tick(
        cfg=cfg,
        scan_symbols=["AAA-USD", "BBB-USD"],
        cycle_symbols=["AAA-USD"],
        open_symbols=["CCC-USD"],
        stale_symbols=["BBB-USD", "CCC-USD"],
    )
    assert selected == ["AAA-USD", "BBB-USD"]


def test_build_ingestion_freshness_ledger_reports_stale_rows(monkeypatch):
    class _Store:
        def list_sync_states(self, *, symbols=None, timeframes=None):
            return [
                {
                    "symbol": "AAA-USD",
                    "timeframe": "1m",
                    "latest_ms": 1_000_000,
                    "last_sync_ms": 1_000_000,
                    "status": "ok",
                    "note": "",
                },
            ]

    monkeypatch.setattr(bot_main, "RevolutCandleStore", _Store)
    ledger = bot_main._build_ingestion_freshness_ledger(
        cfg={
            "market_data": {
                "sync_timeframes": ["1m"],
                "decision_candle_timeframe": "1m",
                "sync_cadence_seconds": {"1m": 20},
            }
        },
        symbols=["AAA-USD", "BBB-USD"],
        now_epoch=2_000.0,
    )
    assert ledger["rows_total"] == 2
    assert ledger["stale_rows"] == 2
    assert "AAA-USD" in ledger["decision_timeframe_stale_symbols"]
    assert "BBB-USD" in ledger["decision_timeframe_stale_symbols"]


def test_symbols_for_scan_prefers_active_tiers_and_keeps_open_symbols():
    class _Exec:
        @staticmethod
        def open_symbols():
            return ["DOGE-USD"]

    cfg = {
        "symbols": ["BTC-USD", "ETH-USD"],
        "market_data": {
            "active_tiers": ["tier1", "tier2"],
            "symbol_tiers": {
                "tier1": ["BTC-USD"],
                "tier2": ["SOL-USD"],
                "tier3": ["XRP-USD"],
            },
        },
    }

    symbols = bot_main._symbols_for_scan(cfg, _Exec())
    assert symbols == ["BTC-USD", "SOL-USD", "DOGE-USD"]


def test_symbols_for_scan_promotes_top_inactive_tier_symbols(tmp_path: Path, monkeypatch):
    state_dir = tmp_path / "state"
    state_dir.mkdir(parents=True, exist_ok=True)
    _seed_state_files(state_dir)
    write_json_file(
        state_dir / "strategy_state.json",
        {
            "last_score": {
                "XRP-USD": 92,
                "ADA-USD": 84,
            },
            "last_volatility": {
                "XRP-USD": 0.02,
                "ADA-USD": 0.01,
            },
        },
    )
    monkeypatch.setattr(bot_main, "STATE_DIR", state_dir)

    cfg = {
        "symbols": ["BTC-USD"],
        "market_data": {
            "active_tiers": ["tier1"],
            "symbol_tiers": {
                "tier1": ["BTC-USD"],
                "tier3": ["XRP-USD", "ADA-USD"],
            },
            "dynamic_tiering_enabled": True,
            "dynamic_tier_promotion_count": 1,
        },
    }
    symbols = bot_main._symbols_for_scan(cfg, executor=None)
    assert symbols == ["BTC-USD", "XRP-USD"]


def test_symbols_for_scan_dynamic_tiering_can_be_disabled():
    cfg = {
        "symbols": ["BTC-USD"],
        "market_data": {
            "active_tiers": ["tier1"],
            "symbol_tiers": {
                "tier1": ["BTC-USD"],
                "tier3": ["XRP-USD", "ADA-USD"],
            },
            "dynamic_tiering_enabled": False,
            "dynamic_tier_promotion_count": 2,
        },
    }
    symbols = bot_main._symbols_for_scan(cfg, executor=None)
    assert symbols == ["BTC-USD"]


def test_apply_adaptive_sync_request_budget_reduces_cap_under_pressure(monkeypatch):
    cfg = {
        "market_data": {
            "max_sync_requests_per_tick": 8,
            "min_sync_requests_per_tick_under_pressure": 1,
            "sync_pressure_window_seconds": 60,
            "sync_pressure_rate_limit_threshold": 3,
            "sync_pressure_throttle_sleep_seconds": 5,
        }
    }
    monkeypatch.setattr(
        bot_main,
        "get_public_api_health",
        lambda window_seconds=60.0: {
            "window_seconds": window_seconds,
            "rate_limited_count": 4,
            "throttle_sleep_seconds_sum": 1.0,
            "throttle_event_count": 1,
        },
    )
    summary = bot_main._apply_adaptive_sync_request_budget(cfg)
    assert summary["under_pressure"] is True
    assert summary["base_cap"] == 8
    assert summary["effective_cap"] == 4
    assert cfg["market_data"]["max_sync_requests_per_tick"] == 4


def test_apply_adaptive_sync_request_budget_keeps_cap_when_healthy(monkeypatch):
    cfg = {
        "market_data": {
            "max_sync_requests_per_tick": 6,
            "min_sync_requests_per_tick_under_pressure": 1,
            "sync_pressure_window_seconds": 60,
            "sync_pressure_rate_limit_threshold": 3,
            "sync_pressure_throttle_sleep_seconds": 5,
        }
    }
    monkeypatch.setattr(
        bot_main,
        "get_public_api_health",
        lambda window_seconds=60.0: {
            "window_seconds": window_seconds,
            "rate_limited_count": 0,
            "throttle_sleep_seconds_sum": 0.0,
            "throttle_event_count": 0,
        },
    )
    summary = bot_main._apply_adaptive_sync_request_budget(cfg)
    assert summary["under_pressure"] is False
    assert summary["effective_cap"] == 6
    assert cfg["market_data"]["max_sync_requests_per_tick"] == 6


def test_non_mr_route_guard_blocks_low_confidence():
    decision = {
        "effective_route": "TREND_PULLBACK",
        "detected_regime_confidence_score": 50,
        "detected_regime_stability_score": 80,
        "detected_regime_persistence_score": 80,
        "regime_data_quality_status": "GOOD",
    }
    market = {"core_candle_readiness": {"ready": True}}
    cfg = {"market_data": {"route_quality_guard_enabled": True}}
    ok, reason = bot_main._non_mr_route_guard(
        symbol="BTC-USD",
        decision=decision,
        market=market,
        cfg=cfg,
        now_epoch=1000.0,
        pressure={"rate_limited_count": 0},
    )
    assert ok is False
    assert reason == "route_quality_low_confidence"


def test_non_mr_route_guard_blocks_when_route_exposure_cap_hit(monkeypatch):
    decision = {
        "effective_route": "TREND_PULLBACK",
        "detected_regime_confidence_score": 95,
        "detected_regime_stability_score": 90,
        "detected_regime_persistence_score": 90,
        "regime_data_quality_status": "GOOD",
    }
    market = {"core_candle_readiness": {"ready": True}, "spread_bps": 10, "trade_count": 30}
    cfg = {
        "market_data": {
            "route_quality_guard_enabled": True,
            "route_quality_max_route_share_pct": {"trend_pullback": 20},
        }
    }

    monkeypatch.setattr(
        bot_main,
        "load_route_quality_report_cached",
        lambda **kwargs: {"current": {"effective_route_counts": {"trend_pullback": 8, "mean_reversion": 2}}},
    )
    bot_main._route_guard_cap_hits.clear()
    ok, reason = bot_main._non_mr_route_guard(
        symbol="BTC-USD",
        decision=decision,
        market=market,
        cfg=cfg,
        now_epoch=1000.0,
        pressure={"rate_limited_count": 0},
    )
    assert ok is False
    assert str(reason).startswith("route_exposure_cap:trend_pullback:")


def test_non_mr_route_guard_triggers_and_honors_route_cooldown(tmp_path: Path, monkeypatch):
    state_dir = tmp_path / "state"
    state_dir.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(bot_main, "STATE_DIR", state_dir)
    write_json_file(
        state_dir / "trades.json",
        [
            {"time": 100.0, "side": "SELL", "symbol": "A", "effective_route": "trend_pullback", "pnl": -1.0},
            {"time": 90.0, "side": "SELL", "symbol": "B", "effective_route": "trend_pullback", "pnl": -0.5},
            {"time": 80.0, "side": "SELL", "symbol": "C", "effective_route": "trend_pullback", "pnl": 0.2},
        ],
    )
    decision = {
        "effective_route": "TREND_PULLBACK",
        "detected_regime_confidence_score": 95,
        "detected_regime_stability_score": 90,
        "detected_regime_persistence_score": 90,
        "regime_data_quality_status": "GOOD",
    }
    market = {"core_candle_readiness": {"ready": True}, "spread_bps": 10, "trade_count": 30}
    cfg = {
        "market_data": {
            "route_quality_guard_enabled": True,
            "route_quality_max_consecutive_losses": {"trend_pullback": 2},
            "route_quality_cooldown_seconds_after_losses": {"trend_pullback": 60},
        }
    }
    bot_main._route_guard_cooldown_until.clear()
    bot_main._route_guard_loss_streak_cache["mtime"] = None
    bot_main._route_guard_loss_streak_cache["computed_at"] = 0.0
    bot_main._route_guard_loss_streak_cache["streaks"] = {}

    ok, reason = bot_main._non_mr_route_guard(
        symbol="BTC-USD",
        decision=decision,
        market=market,
        cfg=cfg,
        now_epoch=200.0,
        pressure={"rate_limited_count": 0},
    )
    assert ok is False
    assert reason == "route_cooldown_triggered:trend_pullback:2"

    ok2, reason2 = bot_main._non_mr_route_guard(
        symbol="BTC-USD",
        decision=decision,
        market=market,
        cfg=cfg,
        now_epoch=220.0,
        pressure={"rate_limited_count": 0},
    )
    assert ok2 is False
    assert str(reason2).startswith("route_cooldown_active:trend_pullback:")


def test_symbol_health_watchlist_sets_cooldown():
    bot_main._symbol_watchlist_until.clear()
    market = {
        "data_quality_status": "STALE",
        "spread_bps": 250.0,
        "core_candle_readiness": {"ready": False},
    }
    cfg = {"market_data": {"symbol_health_min_score": 50, "symbol_health_watchlist_seconds": 600}}
    result = bot_main._update_symbol_health("ABC-USD", market, cfg, 500.0)
    assert result["watchlisted"] is True
    assert bot_main._symbol_watchlist_until["ABC-USD"] >= 1100.0


def test_append_decision_audit_writes_jsonl(tmp_path: Path, monkeypatch):
    state_dir = tmp_path / "state"
    state_dir.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(bot_main, "STATE_DIR", state_dir)
    monkeypatch.setattr(bot_main, "DECISION_AUDIT_PATH", state_dir / "decision_audit.jsonl")

    bot_main._append_decision_audit(
        symbol="BTC-USD",
        market={
            "price": 100.0,
            "data_quality_status": "GOOD",
            "snapshot_version": 4,
            "snapshot_ts_epoch": 1700000000.0,
            "candle_timeframe": "1m",
            "candle_last_update_ts": 1700000000000,
            "candle_age_seconds": 510.0,
            "candle_stale_after_seconds": 420.0,
            "candle_age_over_stale_ratio": 1.214285,
            "strategy_eval_gate": {
                "allowed": False,
                "blocked_reason": "market_data_quality:stale",
                "snapshot_age_seconds": 9.5,
            },
        },
        decision={"action": "HOLD", "effective_route": "MEAN_REVERSION", "reason": "market_data_quality:stale"},
        executed=False,
        blocked_reason=None,
        decision_context_audit={
            "strategy_eval_allowed": False,
            "blocked_reason": "market_data_quality:stale",
            "market_snapshot_age_seconds": 9.5,
        },
    )
    text = (state_dir / "decision_audit.jsonl").read_text(encoding="utf-8").strip()
    assert "\"schema_name\": \"decision_audit\"" in text
    assert "\"symbol\": \"BTC-USD\"" in text
    row = json.loads(text)
    assert row["market_snapshot_version"] == 4
    assert row["candle_age_seconds"] == 510.0
    assert row["candle_stale_after_seconds"] == 420.0
    assert row["strategy_eval_gate_allowed"] is False
    assert row["strategy_eval_snapshot_age_seconds"] == 9.5
    assert row["decision_context_allowed"] is False
    assert row["gate_trigger_condition"] == "candle_age_seconds > candle_stale_after_seconds"
    assert row["gate_trigger_threshold"] == 420.0
    assert row["gate_trigger_actual"] == 510.0
    assert row["gate_trigger_correct"] is True


def test_read_decision_audit_rows_infers_legacy_schema(tmp_path: Path, monkeypatch):
    state_dir = tmp_path / "state"
    state_dir.mkdir(parents=True, exist_ok=True)
    audit_path = state_dir / "decision_audit.jsonl"
    monkeypatch.setattr(bot_main, "DECISION_AUDIT_PATH", audit_path)

    audit_path.write_text('{"symbol":"BTC-USD","action":"HOLD"}\n', encoding="utf-8")
    rows = bot_main.read_decision_audit_rows()
    assert len(rows) == 1
    assert rows[0]["schema_name"] == "decision_audit"
    assert rows[0]["schema_version"] == 1
    assert rows[0]["_legacy_schema_inferred"] is True


def test_resolve_decision_gate_diagnostics_for_insufficient_data():
    result = bot_main._resolve_decision_gate_diagnostics(
        decision_reason="insufficient_data",
        market={"atr_raw": 0.0},
        cfg={},
    )
    assert result["condition"] == "atr_raw > 0"
    assert result["threshold"] == 0.0
    assert result["actual"] == 0.0
    assert result["correct"] is True


def test_resolve_decision_gate_diagnostics_for_stale_market():
    result = bot_main._resolve_decision_gate_diagnostics(
        decision_reason="market_data_quality:stale",
        market={"candle_age_seconds": 600.0, "candle_stale_after_seconds": 420.0},
        cfg={},
    )
    assert result["condition"] == "candle_age_seconds > candle_stale_after_seconds"
    assert result["threshold"] == 420.0
    assert result["actual"] == 600.0
    assert result["correct"] is True


def test_persist_market_sync_health_writes_snapshot_and_history(tmp_path: Path, monkeypatch):
    state_dir = tmp_path / "state"
    state_dir.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(bot_main, "STATE_DIR", state_dir)
    monkeypatch.setattr(bot_main, "MARKET_SYNC_HEALTH_PATH", state_dir / "market_sync_health.json")
    monkeypatch.setattr(
        bot_main,
        "MARKET_SYNC_HEALTH_HISTORY_PATH",
        state_dir / "market_sync_health_history.jsonl",
    )

    payload = {
        "ts_epoch": 123.45,
        "sync": {"requests": 4, "new_inserted": 100},
        "coverage": {"fresh_counts_by_timeframe": {"1h": 5, "4h": 2, "1d": 1}},
    }
    ok = bot_main._persist_market_sync_health(payload)
    assert ok is True
    assert (state_dir / "market_sync_health.json").exists()
    history = (state_dir / "market_sync_health_history.jsonl").read_text(encoding="utf-8").strip().splitlines()
    assert len(history) == 1
    assert "\"requests\": 4" in history[0]


def test_persist_market_sync_health_stringifies_non_json_values(tmp_path: Path, monkeypatch):
    state_dir = tmp_path / "state"
    state_dir.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(bot_main, "STATE_DIR", state_dir)
    monkeypatch.setattr(bot_main, "MARKET_SYNC_HEALTH_PATH", state_dir / "market_sync_health.json")
    monkeypatch.setattr(
        bot_main,
        "MARKET_SYNC_HEALTH_HISTORY_PATH",
        state_dir / "market_sync_health_history.jsonl",
    )

    payload = {
        "ts_epoch": 123.45,
        "bad": Path("x"),
    }
    ok = bot_main._persist_market_sync_health(payload)
    assert ok is True
    text = (state_dir / "market_sync_health.json").read_text(encoding="utf-8")
    assert "\"bad\": \"x\"" in text


def test_run_housekeeping_trims_history_and_audit(tmp_path: Path, monkeypatch):
    state_dir = tmp_path / "state"
    snapshots_dir = state_dir / "snapshots"
    snapshots_dir.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(bot_main, "STATE_DIR", state_dir)
    monkeypatch.setattr(bot_main, "MARKET_SYNC_HEALTH_HISTORY_PATH", state_dir / "market_sync_health_history.jsonl")
    monkeypatch.setattr(bot_main, "DECISION_AUDIT_PATH", state_dir / "decision_audit.jsonl")

    (state_dir / "market_sync_health_history.jsonl").write_text(
        "\n".join(
            [
                "{\"ts_epoch\": 1}",
                "{\"ts_epoch\": 2}",
                "{\"ts_epoch\": 3}",
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    (state_dir / "decision_audit.jsonl").write_text(
        "\n".join(["{\"x\":1}", "{\"x\":2}", "{\"x\":3}"]) + "\n",
        encoding="utf-8",
    )
    old_snap = snapshots_dir / "old"
    old_snap.mkdir(parents=True, exist_ok=True)
    (old_snap / "a.txt").write_text("x", encoding="utf-8")

    cfg = {
        "market_data": {
            "sync_health_history_max_lines": 2,
            "sync_health_history_retention_days": 0,
            "decision_audit_max_lines": 2,
            "snapshot_retention_days": 0,
            "snapshot_max_dirs": 0,
        }
    }
    result = bot_main._run_housekeeping(cfg)
    assert result["removed_sync_history_lines"] >= 1
    assert result["removed_decision_audit_lines"] >= 1
    assert "jsonl_size_pruned_files" in result


def test_build_sync_slo_degrades_when_decision_timeframe_freshness_breaches():
    cfg = {
        "market_data": {
            "decision_candle_timeframe": "1m",
            "decision_candle_stale_intervals": 6,
            "decision_candle_min_stale_seconds": 420,
            "freshness_slo": {
                "min_fresh_1h": 1,
                "min_fresh_4h": 1,
                "min_fresh_24h": 0,
                "min_fresh_decision_timeframe": 1,
                "decision_timeframe_enforce": True,
                "decision_timeframe_max_oldest_due_seconds": 420,
                "max_sync_errors": 0,
                "max_degraded_jobs": 0,
                "min_sync_requests": 1,
            },
        }
    }
    sync_summary = {
        "errors": 0,
        "degraded": 0,
        "requests": 2,
        "new_inserted": 5,
        "scheduler": {
            "due_jobs_by_timeframe": {"1m": 5},
            "selected_jobs_by_timeframe": {"1m": 0},
            "oldest_due_age_seconds_by_timeframe": {"1m": 700.0},
        },
    }
    coverage_summary = {
        "fresh_counts_by_timeframe": {"1h": 2, "4h": 2, "1d": 1, "1m": 0},
        "stale_symbol_timeframes": 10,
    }
    slo = bot_main._build_sync_slo(sync_summary, coverage_summary, cfg)
    assert slo["status"] == "DEGRADED"
    assert slo["decision_freshness_ok"] is False
    assert slo["entry_block_reason"] in {
        "decision_fresh_count_below_threshold",
        "decision_oldest_due_age_exceeded",
        "decision_timeframe_starved",
    }
