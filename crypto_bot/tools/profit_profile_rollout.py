from __future__ import annotations

import argparse
import json
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from utils.config_schema import normalize_config
from utils.state_io import read_json_file, write_json_file
from utils.state_paths import resolve_state_dir


@dataclass(frozen=True)
class ConfigUpdate:
    path: str
    value: Any
    rationale: str


PHASE_ORDER = [
    "data_integrity",
    "regime_participation",
    "risk_sizing",
    "execution_realism",
    "runtime_safety",
    "capital_efficiency",
]

PROFILE_ORDER = {
    "conservative": 0,
    "balanced": 1,
    "aggressive": 2,
}

PHASE_UPDATES: dict[str, list[ConfigUpdate]] = {
    "data_integrity": [
        ConfigUpdate(
            "market_data.source_map.candles.allow_snapshot_fallback",
            False,
            "Keep decision-critical candles authoritative only.",
        ),
        ConfigUpdate(
            "market_data.source_map.candles.decision_use_snapshot_fallback",
            False,
            "Avoid stale snapshot fallbacks in decision path.",
        ),
        ConfigUpdate(
            "market_data.freshness_slo.min_fresh_1h",
            1,
            "Require at least one fresh 1h coverage sample.",
        ),
        ConfigUpdate(
            "market_data.freshness_slo.min_fresh_4h",
            1,
            "Require at least one fresh 4h coverage sample.",
        ),
        ConfigUpdate(
            "market_data.freshness_slo.max_degraded_jobs",
            1,
            "Tighten degraded-job tolerance to reduce bad-data trading windows.",
        ),
        ConfigUpdate(
            "market_data.route_quality_guard_enabled",
            True,
            "Keep route quality guard always active.",
        ),
        ConfigUpdate(
            "market_data.route_quality_min_confidence",
            78.0,
            "Raise confidence threshold to filter weak regime routes.",
        ),
        ConfigUpdate(
            "market_data.route_quality_min_stability",
            65.0,
            "Raise stability threshold to reduce route churn.",
        ),
        ConfigUpdate(
            "market_data.route_quality_min_persistence",
            65.0,
            "Raise persistence threshold to reduce transient routing.",
        ),
    ],
    "regime_participation": [
        ConfigUpdate(
            "strategy_defaults.router.auto_use_multitimeframe_advisory",
            True,
            "Make AUTO routing consistently advisory-driven.",
        ),
        ConfigUpdate(
            "strategy_defaults.router.auto_min_confidence",
            72.0,
            "Require higher AUTO confidence before route promotion.",
        ),
        ConfigUpdate(
            "strategy_defaults.router.auto_min_confirmations",
            3,
            "Require additional confirmations to reduce false promotion.",
        ),
        ConfigUpdate(
            "strategy_defaults.router.auto_use_current_cycle_shadow",
            True,
            "Ensure shadow stability participates in current cycle selection.",
        ),
    ],
    "risk_sizing": [
        ConfigUpdate(
            "risk.sizing_mode",
            "auto",
            "Prefer stop-distance sizing when stop data is available while preserving compatibility.",
        ),
        ConfigUpdate(
            "risk.risk_percent",
            0.01,
            "Lower per-trade risk budget for lower-failure profile.",
        ),
        ConfigUpdate(
            "risk.max_loss_per_trade_usd",
            40.0,
            "Hard cap expected loss per trade.",
        ),
        ConfigUpdate(
            "risk.trade_amount_usd",
            150.0,
            "Conservative legacy fallback notional.",
        ),
        ConfigUpdate(
            "risk.max_concurrent_trades",
            12,
            "Limit portfolio concurrency.",
        ),
        ConfigUpdate(
            "risk.max_concurrent_trades_per_token",
            1,
            "Prevent per-symbol stacking risk.",
        ),
        ConfigUpdate(
            "risk.max_trade_amount_usd",
            750.0,
            "Hard cap single-trade amount.",
        ),
        ConfigUpdate(
            "risk.max_notional_usd",
            750.0,
            "Hard cap single-trade notional in sizing contract.",
        ),
        ConfigUpdate(
            "risk.max_portfolio_exposure_pct",
            65.0,
            "Keep portfolio reserve for drawdown resilience.",
        ),
        ConfigUpdate(
            "risk.max_exposure_per_token_pct",
            12.0,
            "Limit symbol concentration risk.",
        ),
        ConfigUpdate(
            "risk.min_trade_notional_usd",
            25.0,
            "Avoid ultra-small/noisy entries.",
        ),
        ConfigUpdate(
            "risk.liquidity_cap_notional_usd",
            500.0,
            "Cap notional by liquidity profile.",
        ),
        ConfigUpdate(
            "risk.block_bad_market_quality",
            True,
            "Never allow entries under bad market quality.",
        ),
    ],
    "execution_realism": [
        ConfigUpdate(
            "paper_execution.enabled",
            True,
            "Force paper fills through execution simulator.",
        ),
        ConfigUpdate(
            "paper_execution.base_slippage_bps",
            4.0,
            "Use conservative baseline slippage.",
        ),
        ConfigUpdate(
            "paper_execution.max_slippage_bps",
            80.0,
            "Cap extreme slippage assumptions.",
        ),
        ConfigUpdate(
            "paper_execution.soft_spread_bps",
            30.0,
            "Start penalizing spread at tighter level.",
        ),
        ConfigUpdate(
            "paper_execution.hard_reject_spread_bps",
            180.0,
            "Reject entries in very wide spread conditions.",
        ),
        ConfigUpdate(
            "paper_execution.min_fill_ratio",
            0.35,
            "Require stronger expected fill quality.",
        ),
        ConfigUpdate(
            "paper_execution.reject_if_fill_ratio_below",
            0.15,
            "Reject low-liquidity fills early.",
        ),
        ConfigUpdate(
            "paper_execution.enable_timeouts",
            True,
            "Keep timeout modeling active.",
        ),
        ConfigUpdate(
            "paper_execution.timeout_ms",
            2000,
            "Slightly tighter timeout for execution realism.",
        ),
        ConfigUpdate(
            "paper_execution.reject_on_bad_data",
            True,
            "Do not execute in bad-data conditions.",
        ),
    ],
    "runtime_safety": [
        ConfigUpdate(
            "risk.daily_loss_limit_usd",
            150.0,
            "Hard daily stop-loss guardrail.",
        ),
        ConfigUpdate(
            "risk.daily_loss_auto_pause",
            True,
            "Pause new buys after daily loss breach.",
        ),
        ConfigUpdate(
            "risk.daily_loss_close_all",
            False,
            "Keep close-all optional; preserve current conservative behavior.",
        ),
        ConfigUpdate(
            "risk.max_consecutive_execution_failures",
            3,
            "Trigger pause sooner on repeated execution failures.",
        ),
        ConfigUpdate(
            "risk.execution_failure_pause_seconds",
            300,
            "Cool-down period after repeated execution failures.",
        ),
    ],
    "capital_efficiency": [
        ConfigUpdate(
            "profit_locks.stale_exit_max_hold_seconds",
            1814400.0,
            "Keep current proven stale-release horizon (21 days) as baseline.",
        ),
        ConfigUpdate(
            "profit_locks.stale_exit_min_pnl_pct",
            0.003,
            "Keep stale-release edge floor stable until more redeploy data accumulates.",
        ),
    ],
}

PROFILE_UPDATES: dict[str, list[ConfigUpdate]] = {
    "conservative": [
        ConfigUpdate("strategy_defaults.tuning_profile", "conservative", "Use conservative strategy profile."),
        ConfigUpdate("risk.risk_percent", 0.01, "Lower per-trade risk budget."),
        ConfigUpdate("risk.max_loss_per_trade_usd", 40.0, "Keep strict per-trade loss cap."),
        ConfigUpdate("risk.trade_amount_usd", 150.0, "Conservative fallback notional."),
        ConfigUpdate("risk.max_concurrent_trades", 12, "Conservative portfolio concurrency."),
        ConfigUpdate("risk.max_trade_amount_usd", 750.0, "Conservative max trade amount."),
        ConfigUpdate("risk.max_portfolio_exposure_pct", 65.0, "Conservative total exposure."),
        ConfigUpdate("risk.max_exposure_per_token_pct", 12.0, "Conservative per-symbol exposure."),
        ConfigUpdate("paper_execution.base_slippage_bps", 4.0, "Conservative execution assumption."),
        ConfigUpdate("paper_execution.hard_reject_spread_bps", 180.0, "Reject wider spreads."),
    ],
    "balanced": [
        ConfigUpdate("strategy_defaults.tuning_profile", "balanced", "Use balanced strategy profile."),
        ConfigUpdate("risk.risk_percent", 0.015, "Balanced per-trade risk budget."),
        ConfigUpdate("risk.max_loss_per_trade_usd", 60.0, "Balanced per-trade loss cap."),
        ConfigUpdate("risk.trade_amount_usd", 225.0, "Balanced fallback notional."),
        ConfigUpdate("risk.max_concurrent_trades", 18, "Balanced portfolio concurrency."),
        ConfigUpdate("risk.max_trade_amount_usd", 1200.0, "Balanced max trade amount."),
        ConfigUpdate("risk.max_portfolio_exposure_pct", 80.0, "Balanced total exposure."),
        ConfigUpdate("risk.max_exposure_per_token_pct", 18.0, "Balanced per-symbol exposure."),
        ConfigUpdate("paper_execution.base_slippage_bps", 3.0, "Balanced execution assumption."),
        ConfigUpdate("paper_execution.hard_reject_spread_bps", 210.0, "Balanced spread reject threshold."),
    ],
    "aggressive": [
        ConfigUpdate("strategy_defaults.tuning_profile", "aggressive", "Use aggressive strategy profile."),
        ConfigUpdate("risk.risk_percent", 0.02, "Higher per-trade risk budget."),
        ConfigUpdate("risk.max_loss_per_trade_usd", 90.0, "Higher per-trade loss cap."),
        ConfigUpdate("risk.trade_amount_usd", 300.0, "Higher fallback notional."),
        ConfigUpdate("risk.max_concurrent_trades", 24, "Higher portfolio concurrency."),
        ConfigUpdate("risk.max_trade_amount_usd", 1800.0, "Higher max trade amount."),
        ConfigUpdate("risk.max_portfolio_exposure_pct", 92.0, "Higher total exposure."),
        ConfigUpdate("risk.max_exposure_per_token_pct", 24.0, "Higher per-symbol exposure."),
        ConfigUpdate("paper_execution.base_slippage_bps", 2.5, "Lower assumed slippage for aggressive profile."),
        ConfigUpdate("paper_execution.hard_reject_spread_bps", 240.0, "Higher spread tolerance."),
    ],
}


def _default_state_dir() -> Path:
    return resolve_state_dir(Path(__file__).resolve().parents[1] / "state")


def _set_path(payload: dict[str, Any], dotted_path: str, value: Any):
    cursor: dict[str, Any] = payload
    segments = dotted_path.split(".")
    for key in segments[:-1]:
        next_val = cursor.get(key)
        if not isinstance(next_val, dict):
            next_val = {}
            cursor[key] = next_val
        cursor = next_val
    cursor[segments[-1]] = value


def _get_path(payload: dict[str, Any], dotted_path: str) -> Any:
    cursor: Any = payload
    for key in dotted_path.split("."):
        if not isinstance(cursor, dict):
            return None
        cursor = cursor.get(key)
    return cursor


def _phase_payload(
    cfg: dict[str, Any],
    phase: str,
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    updates = PHASE_UPDATES.get(phase)
    if not updates:
        raise ValueError(f"Unknown phase: {phase}")
    changed: list[dict[str, Any]] = []
    for update in updates:
        before = _get_path(cfg, update.path)
        if before == update.value:
            continue
        _set_path(cfg, update.path, update.value)
        changed.append(
            {
                "path": update.path,
                "before": before,
                "after": update.value,
                "rationale": update.rationale,
            }
        )
    return cfg, changed


def _current_profile(cfg: dict[str, Any]) -> str:
    strategy_defaults = cfg.get("strategy_defaults", {})
    if not isinstance(strategy_defaults, dict):
        return "conservative"
    profile = str(strategy_defaults.get("tuning_profile") or "").strip().lower()
    if profile in PROFILE_ORDER:
        return profile
    return "conservative"


def _profile_transition_guard(
    *,
    current_profile: str,
    target_profile: str,
    allow_risk_upshift: bool,
    allow_profile_jump: bool,
) -> dict[str, Any]:
    current_rank = PROFILE_ORDER.get(current_profile, PROFILE_ORDER["conservative"])
    target_rank = PROFILE_ORDER.get(target_profile, PROFILE_ORDER["conservative"])
    direction = (
        "same"
        if target_rank == current_rank
        else ("upshift" if target_rank > current_rank else "downshift")
    )
    rank_delta = target_rank - current_rank

    allowed = True
    reason = "ok"
    if rank_delta > 0:
        if not allow_risk_upshift:
            allowed = False
            reason = "risk_upshift_requires_allow_flag"
        elif rank_delta > 1 and not allow_profile_jump:
            allowed = False
            reason = "risk_upshift_requires_staged_transition"

    return {
        "current_profile": current_profile,
        "target_profile": target_profile,
        "direction": direction,
        "rank_delta": rank_delta,
        "allowed": allowed,
        "reason": reason,
    }


def _profile_payload(cfg: dict[str, Any], profile: str) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    updates = PROFILE_UPDATES.get(profile)
    if not updates:
        raise ValueError(f"Unknown profile: {profile}")
    changed: list[dict[str, Any]] = []
    for update in updates:
        before = _get_path(cfg, update.path)
        if before == update.value:
            continue
        _set_path(cfg, update.path, update.value)
        changed.append(
            {
                "path": update.path,
                "before": before,
                "after": update.value,
                "rationale": update.rationale,
            }
        )
    return cfg, changed


def _write_backup(config_path: Path, cfg: dict[str, Any], phase: str) -> Path:
    stamp = time.strftime("%Y%m%d-%H%M%S", time.localtime())
    backup_dir = config_path.parent / "config_backups"
    backup_dir.mkdir(parents=True, exist_ok=True)
    backup_path = backup_dir / f"{stamp}_{phase}.json"
    write_json_file(backup_path, cfg, indent=2)
    return backup_path


def _append_rollout_log(
    *,
    docs_dir: Path,
    phase: str,
    state_dir: Path,
    backup_path: Path,
    changes: list[dict[str, Any]],
    warnings: list[str],
):
    docs_dir.mkdir(parents=True, exist_ok=True)
    log_path = docs_dir / "profit_profile_change_log.jsonl"
    row = {
        "ts_epoch": time.time(),
        "phase": phase,
        "state_dir": str(state_dir),
        "backup_path": str(backup_path),
        "changed_count": len(changes),
        "changes": changes,
        "normalize_warnings": warnings,
    }
    with open(log_path, "a", encoding="utf-8") as handle:
        handle.write(json.dumps(row))
        handle.write("\n")


def _apply_phase(
    *,
    state_dir: Path,
    phase: str,
    dry_run: bool,
) -> dict[str, Any]:
    config_path = state_dir / "config.json"
    cfg = read_json_file(config_path, default={})
    if not isinstance(cfg, dict):
        raise ValueError(f"Invalid config at {config_path}")

    previous_cfg = json.loads(json.dumps(cfg))
    cfg, changed = _phase_payload(cfg, phase)
    normalized_cfg, warnings, _changed_by_normalization = normalize_config(cfg, strict=False)

    result = {
        "phase": phase,
        "state_dir": str(state_dir),
        "changed_count": len(changed),
        "changes": changed,
        "normalize_warnings": warnings,
        "dry_run": dry_run,
    }
    if dry_run:
        return result

    backup_path = _write_backup(config_path, previous_cfg, phase)
    write_json_file(config_path, normalized_cfg, indent=2)
    docs_dir = Path(__file__).resolve().parents[2] / "docs"
    _append_rollout_log(
        docs_dir=docs_dir,
        phase=phase,
        state_dir=state_dir,
        backup_path=backup_path,
        changes=changed,
        warnings=warnings,
    )
    result["backup_path"] = str(backup_path)
    return result


def _apply_profile(
    *,
    state_dir: Path,
    profile: str,
    dry_run: bool,
    allow_risk_upshift: bool,
    allow_profile_jump: bool,
) -> dict[str, Any]:
    config_path = state_dir / "config.json"
    cfg = read_json_file(config_path, default={})
    if not isinstance(cfg, dict):
        raise ValueError(f"Invalid config at {config_path}")

    previous_cfg = json.loads(json.dumps(cfg))
    current_profile = _current_profile(cfg)
    transition = _profile_transition_guard(
        current_profile=current_profile,
        target_profile=profile,
        allow_risk_upshift=allow_risk_upshift,
        allow_profile_jump=allow_profile_jump,
    )

    cfg, changed = _profile_payload(cfg, profile)
    normalized_cfg, warnings, _changed_by_normalization = normalize_config(cfg, strict=False)

    result = {
        "mode": "profile",
        "profile": profile,
        "state_dir": str(state_dir),
        "changed_count": len(changed),
        "changes": changed,
        "normalize_warnings": warnings,
        "dry_run": dry_run,
        "transition_guard": transition,
    }
    if dry_run:
        return result

    if not bool(transition.get("allowed")):
        reason = str(transition.get("reason") or "transition_not_allowed")
        raise ValueError(f"Profile transition blocked: {reason}")

    backup_path = _write_backup(config_path, previous_cfg, f"profile_{profile}")
    write_json_file(config_path, normalized_cfg, indent=2)
    docs_dir = Path(__file__).resolve().parents[2] / "docs"
    _append_rollout_log(
        docs_dir=docs_dir,
        phase=f"profile:{profile}",
        state_dir=state_dir,
        backup_path=backup_path,
        changes=changed,
        warnings=warnings,
    )
    result["backup_path"] = str(backup_path)
    return result


def _save_summary(results: list[dict[str, Any]], *, docs_dir: Path):
    docs_dir.mkdir(parents=True, exist_ok=True)
    stamp = time.strftime("%Y-%m-%d_%H%M%S", time.localtime())
    summary_path = docs_dir / f"profit_profile_apply_{stamp}.json"
    payload = {
        "generated_at_epoch": time.time(),
        "phases": results,
    }
    write_json_file(summary_path, payload, indent=2)
    return summary_path


def main() -> int:
    parser = argparse.ArgumentParser(description="Apply step-by-step low-failure profit profile phases.")
    parser.add_argument(
        "--state-dir",
        default=str(_default_state_dir()),
        help="Runtime state directory containing config.json",
    )
    parser.add_argument(
        "--phase",
        choices=PHASE_ORDER + ["all"],
        default="all",
        help="Single phase or all phases in safe order.",
    )
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument(
        "--profile",
        choices=list(PROFILE_ORDER.keys()),
        help="Apply a named risk profile with transition guardrails.",
    )
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Persist profile changes. Without this flag, profile mode is preview-only.",
    )
    parser.add_argument(
        "--allow-risk-upshift",
        action="store_true",
        help="Allow moving from a lower-risk profile to a higher-risk profile.",
    )
    parser.add_argument(
        "--allow-profile-jump",
        action="store_true",
        help="Allow skipping profile levels when moving upward (e.g., conservative -> aggressive).",
    )
    parser.add_argument("--print-json", action="store_true")
    args = parser.parse_args()

    state_dir = Path(args.state_dir)
    if not state_dir.exists():
        raise FileNotFoundError(f"State directory not found: {state_dir}")

    results: list[dict[str, Any]] = []
    if args.profile:
        if args.phase != "all":
            raise ValueError("Cannot combine --profile with --phase. Use one mode per run.")
        profile_dry_run = bool(args.dry_run or not args.apply)
        results.append(
            _apply_profile(
                state_dir=state_dir,
                profile=str(args.profile),
                dry_run=profile_dry_run,
                allow_risk_upshift=bool(args.allow_risk_upshift),
                allow_profile_jump=bool(args.allow_profile_jump),
            )
        )
        selected_phases = [f"profile:{args.profile}"]
    else:
        selected_phases = PHASE_ORDER if args.phase == "all" else [args.phase]
        for phase in selected_phases:
            results.append(
                _apply_phase(
                    state_dir=state_dir,
                    phase=phase,
                    dry_run=bool(args.dry_run),
                )
            )

    docs_dir = Path(__file__).resolve().parents[2] / "docs"
    summary_path = _save_summary(results, docs_dir=docs_dir)
    output = {
        "state_dir": str(state_dir),
        "dry_run": bool(args.dry_run),
        "applied_phases": selected_phases,
        "summary_path": str(summary_path),
        "results": results,
    }

    if args.print_json:
        print(json.dumps(output, indent=2))
    else:
        print(f"Profit profile rollout complete: {summary_path}")
        for row in results:
            print(f"- {row['phase']}: changed={row['changed_count']} dry_run={row['dry_run']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
