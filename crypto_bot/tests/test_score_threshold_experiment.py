from __future__ import annotations

import importlib.util
from pathlib import Path


def _load_module():
    repo = Path(__file__).resolve().parents[2]
    mod_path = repo / "crypto_bot" / "tools" / "score_threshold_experiment.py"
    spec = importlib.util.spec_from_file_location("score_threshold_experiment", mod_path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Unable to load module spec from {mod_path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_apply_threshold_updates_all_contract_keys():
    mod = _load_module()
    cfg = {
        "market_regime": {"min_score_to_buy": 50},
        "volatility_scalper": {"min_score_to_buy": 55},
        "min_score_to_buy": 50,
    }
    before, after = mod._apply_threshold(cfg, 46.0)  # noqa: SLF001

    assert before["market_regime.min_score_to_buy"] == 50.0
    assert before["min_score_to_buy"] == 50.0
    assert before["volatility_scalper.min_score_to_buy"] == 55.0
    assert after["market_regime.min_score_to_buy"] == 46.0
    assert after["min_score_to_buy"] == 46.0
    assert after["volatility_scalper.min_score_to_buy"] == 46.0


def test_build_comparison_computes_expected_deltas():
    mod = _load_module()
    before = {
        "execution_attempts": 2,
        "executed_opportunity_rate_pct": 1.0,
        "trades_executed": 1,
        "entry_blocked_cycles": 100,
        "realized_net_pnl_usd": 0.1,
        "max_drawdown_pct": 0.8,
    }
    after = {
        "execution_attempts": 5,
        "executed_opportunity_rate_pct": 2.5,
        "trades_executed": 2,
        "entry_blocked_cycles": 90,
        "realized_net_pnl_usd": 0.15,
        "max_drawdown_pct": 0.6,
    }
    cmp = mod._build_comparison(before, after)  # noqa: SLF001
    assert cmp["execution_attempts_delta"] == 3.0
    assert cmp["executed_opportunity_rate_pct_delta"] == 1.5
    assert cmp["trades_executed_delta"] == 1.0
    assert cmp["entry_blocked_cycles_delta"] == -10.0
    assert cmp["realized_net_pnl_usd_delta"] == 0.05
    assert cmp["max_drawdown_pct_delta"] == -0.2
