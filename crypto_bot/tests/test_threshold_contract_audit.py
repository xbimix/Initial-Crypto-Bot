from __future__ import annotations

import importlib.util
from pathlib import Path


def _load_module():
    repo = Path(__file__).resolve().parents[2]
    mod_path = repo / "crypto_bot" / "tools" / "threshold_contract_audit.py"
    spec = importlib.util.spec_from_file_location("threshold_contract_audit", mod_path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Unable to load module spec from {mod_path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_threshold_contract_audit_counts_mismatch_and_population():
    mod = _load_module()
    cfg = {
        "market_regime": {"min_score_to_buy": 46, "min_z_score": -1.3},
        "volatility_scalper": {"min_score_to_buy": 48, "entry_z_score_max": -0.2},
        "min_score_to_buy": 46,
    }
    rows = [
        {
            "ts_epoch": 110.0,
            "action": "HOLD",
            "buy_route_name": "mean_reversion",
            "buy_score_actual": 44.5,
            "buy_score_threshold": 46.0,
            "buy_zscore_threshold": -1.3,
        },
        {
            "ts_epoch": 120.0,
            "action": "HOLD",
            "buy_route_name": "volatility_scalper",
            "buy_score_actual": 47.0,
            "buy_score_threshold": 46.0,  # mismatch for scalper (expected 48)
            "buy_zscore_threshold": -0.2,
        },
        {
            "ts_epoch": 130.0,
            "action": "HOLD",
            "buy_route_name": "breakout_momentum",
            "buy_score_actual": None,
            "buy_score_threshold": 46.0,
            "buy_zscore_threshold": -1.3,
        },
    ]
    report = mod.build_threshold_contract_report(cfg=cfg, rows=rows, start_ts=100.0, end_ts=200.0)
    totals = report["totals"]

    assert totals["total_buy_eval_rows"] == 3
    assert totals["buy_score_actual_populated"] == 2
    assert totals["buy_score_threshold_populated"] == 3
    assert totals["buy_zscore_threshold_populated"] == 3
    assert totals["buy_score_threshold_mismatch"] == 1
    assert totals["buy_zscore_threshold_mismatch"] == 0

    scalper = report["by_route"]["volatility_scalper"]
    assert scalper["count"] == 1
    assert scalper["score_threshold_mismatch"] == 1


def test_threshold_contract_audit_expected_thresholds():
    mod = _load_module()
    cfg = {
        "market_regime": {"min_score_to_buy": 45, "min_z_score": -1.1},
        "volatility_scalper": {"min_score_to_buy": 49},
        "min_score_to_buy": 44,
    }
    report = mod.build_threshold_contract_report(cfg=cfg, rows=[], start_ts=0.0, end_ts=10.0)
    expected = report["expected_thresholds"]
    assert expected["mean_reversion_score"] == 45.0
    assert expected["trend_pullback_score"] == 45.0
    assert expected["breakout_momentum_score"] == 45.0
    assert expected["volatility_scalper_score"] == 49.0
    assert expected["mean_reversion_zscore"] == -1.1
    # falls back to default when not configured for scalper
    assert expected["volatility_scalper_zscore"] == -0.1
