from __future__ import annotations

import importlib.util
from pathlib import Path


def _load_module():
    repo = Path(__file__).resolve().parents[2]
    mod_path = repo / "crypto_bot" / "tools" / "critical_strategy_canary.py"
    spec = importlib.util.spec_from_file_location("critical_strategy_canary", mod_path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Unable to load module spec from {mod_path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _base_cfg() -> dict:
    return {
        "market_regime": {
            "preferred_buy_zone": [-0.1, 0.5],
            "min_score_to_buy": 45.0,
            "min_z_score": -1.3,
        },
        "volatility_scalper": {"min_score_to_buy": 45.0},
        "min_score_to_buy": 45.0,
        "risk": {"daily_loss_limit_pct": 2.0},
        "paper_execution": {"enabled": True, "taker_fee_bps": 12.0},
        "profit_locks": {"enabled": True, "trailing_stop_pct": 10.0},
    }


def test_apply_canary_a_updates_buy_zone_only():
    mod = _load_module()
    cfg = _base_cfg()
    before, after = mod._apply_canary_update(cfg, "A", target_value=0.55)  # noqa: SLF001
    assert before["market_regime.preferred_buy_zone.high"] == 0.5
    assert after["market_regime.preferred_buy_zone.high"] == 0.55
    assert after["market_regime.min_score_to_buy"] == 45.0
    assert after["market_regime.min_z_score"] == -1.3
    assert after["min_score_to_buy"] == 45.0
    assert after["volatility_scalper.min_score_to_buy"] == 45.0


def test_apply_canary_b_updates_all_score_contract_keys():
    mod = _load_module()
    cfg = _base_cfg()
    before, after = mod._apply_canary_update(cfg, "B", target_value=43.0)  # noqa: SLF001
    assert before["market_regime.min_score_to_buy"] == 45.0
    assert before["min_score_to_buy"] == 45.0
    assert before["volatility_scalper.min_score_to_buy"] == 45.0
    assert after["market_regime.min_score_to_buy"] == 43.0
    assert after["min_score_to_buy"] == 43.0
    assert after["volatility_scalper.min_score_to_buy"] == 43.0


def test_apply_canary_c_updates_zscore_only():
    mod = _load_module()
    cfg = _base_cfg()
    _before, after = mod._apply_canary_update(cfg, "C", target_value=-1.1)  # noqa: SLF001
    assert after["market_regime.min_z_score"] == -1.1
    assert after["market_regime.min_score_to_buy"] == 45.0
    assert after["min_score_to_buy"] == 45.0


def test_build_comparison_uses_target_reason_share():
    mod = _load_module()
    before = {
        "execution_attempts": 1,
        "executed_opportunity_rate_pct": 2.0,
        "trades_executed": 1,
        "entry_blocked_cycles": 20,
        "realized_net_pnl_usd": 1.0,
        "max_drawdown_pct": 1.2,
        "reason_pct_total": {"price_above_buy_zone": 40.0},
    }
    after = {
        "execution_attempts": 4,
        "executed_opportunity_rate_pct": 3.0,
        "trades_executed": 2,
        "entry_blocked_cycles": 15,
        "realized_net_pnl_usd": 1.2,
        "max_drawdown_pct": 1.1,
        "reason_pct_total": {"price_above_buy_zone": 32.0},
    }
    cmp = mod._build_comparison(before, after, "price_above_buy_zone")  # noqa: SLF001
    assert cmp["execution_attempts_delta"] == 3.0
    assert cmp["target_reason_share_before_pct"] == 40.0
    assert cmp["target_reason_share_after_pct"] == 32.0
    assert cmp["target_reason_share_delta_pct"] == -8.0


def test_promotion_checks_require_invariants_and_green_data():
    mod = _load_module()
    comparison = {
        "execution_attempts_delta": 2.0,
        "target_reason_share_delta_pct": -3.0,
        "max_drawdown_pct_delta": 0.0,
    }
    guard = {
        "risk_unchanged": True,
        "paper_execution_unchanged": False,
        "exit_unchanged": True,
    }
    slo = {
        "slo_status": "OK",
        "decision_freshness_ok": True,
        "quality_ok": True,
        "throughput_ok": True,
    }
    db = {"db_null_close_time": 0, "db_duplicate_primary_rows": 0}
    checks = mod._build_promotion_checks(  # noqa: SLF001
        comparison=comparison,
        guard_checks=guard,
        slo_snapshot=slo,
        db_snapshot=db,
    )
    assert checks["execution_attempts_up"] is True
    assert checks["rejection_mix_improved"] is True
    assert checks["drawdown_not_worse"] is True
    assert checks["paper_execution_unchanged"] is False
    assert checks["all_pass"] is False
