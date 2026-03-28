from __future__ import annotations

from pathlib import Path

import pytest

from strategy import strategy_engine as se
from strategy import strategy_runtime_state as rt
from strategy import regime_engine_v2 as rev2
from utils.state_io import write_json_file


def _snapshot(**overrides):
    base = {
        "symbol": "TEST-USD",
        "price": 100.0,
        "trade_count": 30,
        "spread_bps": 18.0,
        "momentum_norm": 0.45,
        "atr": 1.0,
        "high_24h": 110.0,
        "low_24h": 90.0,
        "snapshot_ts_epoch": 1_730_000_000.0,
        "sampling_minutes": 5.0,
        "recent_prices": [100 + (idx * 0.08) for idx in range(320)],
    }
    base.update(overrides)
    return base


def _cfg():
    return {
        "min_trades": 3,
        "token_regimes": {"TEST-USD": "AUTO"},
        "market_regime": {
            "preferred_buy_zone": [0.05, 0.30],
            "min_z_score": -1.5,
            "min_score_to_buy": 0,
            "blocked_regimes": [],
            "hard_blocked_regimes": [],
        },
        "volatility_filters": {"min_atr": 0.0003, "min_atr_pct": 0.0003},
        "profit_locks": {
            "first_activation": 0.02,
            "initial_lock": 0.01,
            "levels": [[0.04, 0.03], [0.05, 0.04], [0.06, 0.05], [0.08, 0.06]],
            "trailing_activation": 0.10,
            "trailing_gap": 0.02,
            "reset_below_activation": True,
            "max_negative_z_score": -3.5,
        },
        "strategy_defaults": {
            "router": {
                "auto_use_multitimeframe_advisory": True,
                "auto_use_route_quality_gates": False,
            }
        },
    }


@pytest.fixture(autouse=True)
def reset_strategy_globals(monkeypatch, tmp_path: Path):
    for mapping_name in (
        "_last_signal",
        "_last_sell_price",
        "_entry_price",
        "_entry_time",
        "_entry_route",
        "_entry_regime",
        "_exit_policy",
        "_entry_confidence",
        "_entry_timestamp",
        "_entry_route_eval_ts",
        "_entry_regime_eval_ts",
        "_profit_lock",
        "_peak_pnl",
        "_last_momentum",
        "_last_regime",
        "_last_score",
        "_last_volatility",
        "_last_decision_diagnostics",
        "_pending_entry_contract",
        "_shadow_regime_state",
    ):
        getattr(rt, mapping_name).clear()

    state_dir = tmp_path / "state"
    state_dir.mkdir(parents=True, exist_ok=True)
    write_json_file(state_dir / "trades.json", [])
    write_json_file(state_dir / "strategy_state.json", {})
    write_json_file(state_dir / "paper_state.json", {"positions": {}, "balance": 10000})

    monkeypatch.setattr(se, "STATE_DIR", state_dir)
    monkeypatch.setattr(se, "STRATEGY_STATE_FILE", state_dir / "strategy_state.json")
    monkeypatch.setattr(se, "PAPER_STATE_FILE", state_dir / "paper_state.json")
    monkeypatch.setattr(se, "_synced", True)
    monkeypatch.setattr(se, "_last_paper_state_mtime", None)
    monkeypatch.setattr(se, "_metrics_dirty", False)
    monkeypatch.setattr(se, "_last_metrics_flush_at", 0.0)


def test_unified_regime_skips_legacy_when_v2_is_available(monkeypatch):
    calls = {"count": 0}

    def _legacy_probe(*args, **kwargs):
        calls["count"] += 1
        return "dump"

    monkeypatch.setattr(rev2, "detect_regime", _legacy_probe)
    result = rev2.evaluate_regime_unified(snapshot=_snapshot(), now_epoch=1_730_000_050.0, cfg={})

    assert calls["count"] == 0
    assert result["suggestedRegime"] != "MIXED_OR_UNCLEAR"
    assert "legacyRegime" not in result


def test_unified_regime_uses_legacy_only_when_v2_insufficient(monkeypatch):
    monkeypatch.setattr(rev2, "detect_regime", lambda *args, **kwargs: "trend_down")
    result = rev2.evaluate_regime_unified(
        snapshot=_snapshot(recent_prices=[100.0, 99.5, 99.2]),
        now_epoch=1_730_000_050.0,
        cfg={},
    )

    assert result["insufficientData"] is True
    assert result["legacyRegime"] == "trend_down"
    assert result["suggestedRegime"] == rev2.LEGACY_TO_V2["trend_down"]


def test_entry_contract_persists_entry_route_regime_and_exit_policy():
    se.stage_entry_contract(
        "TEST-USD",
        {
            "entry_route": "trend_pullback",
            "entry_regime": "TREND_CONTINUATION",
            "exit_policy": "trend_exit",
            "entry_confidence": 84.0,
            "entry_timestamp": 1000.0,
            "route_eval_ts": 999.0,
            "regime_eval_ts": 998.0,
        },
    )
    se.confirm_entry("TEST-USD", 100.0)

    assert rt._entry_route["TEST-USD"] == "trend_pullback"
    assert rt._entry_regime["TEST-USD"] == "TREND_CONTINUATION"
    assert rt._exit_policy["TEST-USD"] == "trend_exit"
