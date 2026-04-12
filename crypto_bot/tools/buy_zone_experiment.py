from __future__ import annotations

import argparse
import hashlib
import json
import sys
import time
from collections import Counter
from pathlib import Path
from typing import Any

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from utils.state_paths import project_root, resolve_state_dir


EXIT_HOLD_REASONS = {
    "waiting_for_first_lock",
    "in_position",
    "scalper_in_position",
}


def _state_dir() -> Path:
    return resolve_state_dir(project_root() / "crypto_bot" / "state")


def _config_path() -> Path:
    return _state_dir() / "config.json"


def _decision_audit_path() -> Path:
    return _state_dir() / "decision_audit.jsonl"


def _trades_path() -> Path:
    return _state_dir() / "trades.json"


def _experiment_path() -> Path:
    path = _state_dir() / "experiments" / "buy_zone_high_experiment.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


def _reports_dir() -> Path:
    path = _state_dir() / "reports"
    path.mkdir(parents=True, exist_ok=True)
    return path


def _as_float(value: Any, default: float | None = None) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _load_json(path: Path, default: Any) -> Any:
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return default


def _write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def _load_jsonl(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    if not path.exists():
        return rows
    for line in path.read_text(encoding="utf-8", errors="ignore").splitlines():
        text = line.strip()
        if not text:
            continue
        try:
            payload = json.loads(text)
        except Exception:
            continue
        if isinstance(payload, dict):
            rows.append(payload)
    return rows


def _reason(row: dict[str, Any]) -> str:
    for key in (
        "blocked_reason",
        "strategy_eval_gate_blocked_reason",
        "decision_context_blocked_reason",
        "decision_reason",
    ):
        value = str(row.get(key) or "").strip()
        if value:
            return value
    if bool(row.get("executed", False)):
        return "executed"
    return "unknown"


def _window_metrics(
    *,
    start_ts: float,
    end_ts: float,
    decision_rows: list[dict[str, Any]],
    trade_rows: list[dict[str, Any]],
) -> dict[str, Any]:
    scoped_decisions: list[dict[str, Any]] = []
    for row in decision_rows:
        ts = _as_float(row.get("ts_epoch"))
        if ts is None:
            continue
        if ts < start_ts or ts > end_ts:
            continue
        scoped_decisions.append(row)

    total_cycles = len(scoped_decisions)
    executed = sum(1 for row in scoped_decisions if bool(row.get("executed", False)))
    blocked_rows = [row for row in scoped_decisions if not bool(row.get("executed", False))]
    exit_hold_rows = [row for row in blocked_rows if _reason(row) in EXIT_HOLD_REASONS]
    entry_blocked_rows = [row for row in blocked_rows if _reason(row) not in EXIT_HOLD_REASONS]
    entry_opportunities = executed + len(entry_blocked_rows)
    executed_opportunity_rate_pct = (
        (executed / max(entry_opportunities, 1)) * 100.0 if entry_opportunities > 0 else 0.0
    )

    rejection_counts: Counter[str] = Counter(_reason(row) for row in entry_blocked_rows)
    top_rejections = [
        {
            "reason": reason,
            "count": int(count),
            "pct_entry_blocked": round((count / max(len(entry_blocked_rows), 1)) * 100.0, 2),
            "pct_total_cycles": round((count / max(total_cycles, 1)) * 100.0, 2),
        }
        for reason, count in rejection_counts.most_common(12)
    ]

    scoped_trades: list[dict[str, Any]] = []
    for row in trade_rows:
        ts = _as_float(row.get("time"))
        if ts is None:
            continue
        if ts < start_ts or ts > end_ts:
            continue
        scoped_trades.append(row)

    sell_rows = [row for row in scoped_trades if str(row.get("side") or "").strip().upper() == "SELL"]
    realized_net_pnl_usd = sum(_as_float(row.get("pnl"), 0.0) or 0.0 for row in sell_rows)

    balances: list[float] = []
    for row in scoped_trades:
        bal = _as_float(row.get("balance"))
        if bal is None:
            continue
        balances.append(float(bal))

    max_drawdown_pct: float | None = None
    max_drawdown_usd: float | None = None
    if balances:
        peak = balances[0]
        max_dd_usd = 0.0
        max_dd_pct = 0.0
        for value in balances:
            if value > peak:
                peak = value
                continue
            dd_usd = max(peak - value, 0.0)
            dd_pct = (dd_usd / peak * 100.0) if peak > 0 else 0.0
            if dd_usd > max_dd_usd:
                max_dd_usd = dd_usd
            if dd_pct > max_dd_pct:
                max_dd_pct = dd_pct
        max_drawdown_usd = round(max_dd_usd, 6)
        max_drawdown_pct = round(max_dd_pct, 4)

    return {
        "window_start_ts": float(start_ts),
        "window_end_ts": float(end_ts),
        "window_hours": round((end_ts - start_ts) / 3600.0, 4),
        "total_cycles": int(total_cycles),
        "trades_executed": int(executed),
        "entry_blocked_cycles": int(len(entry_blocked_rows)),
        "exit_hold_cycles": int(len(exit_hold_rows)),
        "entry_opportunities": int(entry_opportunities),
        "executed_opportunity_rate_pct": round(executed_opportunity_rate_pct, 4),
        "rejection_mix_top": top_rejections,
        "realized_net_pnl_usd": round(realized_net_pnl_usd, 6),
        "sell_count": int(len(sell_rows)),
        "max_drawdown_pct": max_drawdown_pct,
        "max_drawdown_usd": max_drawdown_usd,
    }


def _hash_dict(value: dict[str, Any] | None) -> str:
    payload = value if isinstance(value, dict) else {}
    text = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _current_buy_zone(cfg: dict[str, Any]) -> list[float]:
    market_regime = cfg.get("market_regime")
    if not isinstance(market_regime, dict):
        market_regime = {}
        cfg["market_regime"] = market_regime
    zone = market_regime.get("preferred_buy_zone")
    if isinstance(zone, list) and len(zone) == 2:
        lo = _as_float(zone[0], 0.05) or 0.05
        hi = _as_float(zone[1], 0.30) or 0.30
        return [float(lo), float(hi)]
    return [0.05, 0.30]


def _apply_buy_zone_high(cfg: dict[str, Any], high: float) -> tuple[list[float], list[float]]:
    before = _current_buy_zone(cfg)
    after = [before[0], float(high)]
    cfg.setdefault("market_regime", {})["preferred_buy_zone"] = after
    return before, after


def _build_comparison(before: dict[str, Any], after: dict[str, Any]) -> dict[str, Any]:
    def _delta(key: str) -> float | None:
        a = _as_float(after.get(key))
        b = _as_float(before.get(key))
        if a is None or b is None:
            return None
        return round(a - b, 6)

    return {
        "executed_opportunity_rate_pct_delta": _delta("executed_opportunity_rate_pct"),
        "entry_blocked_cycles_delta": _delta("entry_blocked_cycles"),
        "trades_executed_delta": _delta("trades_executed"),
        "realized_net_pnl_usd_delta": _delta("realized_net_pnl_usd"),
        "max_drawdown_pct_delta": _delta("max_drawdown_pct"),
        "max_drawdown_usd_delta": _delta("max_drawdown_usd"),
    }


def _load_runtime_inputs() -> tuple[dict[str, Any], list[dict[str, Any]], list[dict[str, Any]]]:
    cfg = _load_json(_config_path(), {})
    if not isinstance(cfg, dict):
        raise ValueError(f"Invalid config payload at {_config_path()}")
    decisions = _load_jsonl(_decision_audit_path())
    trades = _load_json(_trades_path(), [])
    if not isinstance(trades, list):
        trades = []
    return cfg, decisions, trades


def cmd_start(args: argparse.Namespace) -> int:
    now = time.time()
    duration_hours = max(float(args.hours), 0.25)
    end_ts = now + duration_hours * 3600.0
    high = float(args.high)

    record = _load_json(_experiment_path(), {})
    if isinstance(record, dict) and bool(record.get("active")) and _as_float(record.get("end_ts"), 0.0) > now:
        raise RuntimeError("A buy-zone experiment is already active. Finalize or rollback first.")

    cfg, decisions, trades = _load_runtime_inputs()
    before_zone, after_zone = _apply_buy_zone_high(cfg, high)
    risk_hash_before = _hash_dict(cfg.get("risk"))
    exit_hash_before = _hash_dict(cfg.get("profit_locks"))
    _write_json(_config_path(), cfg)

    baseline = _window_metrics(
        start_ts=now - duration_hours * 3600.0,
        end_ts=now,
        decision_rows=decisions,
        trade_rows=trades,
    )

    experiment = {
        "name": "buy_zone_high_timed_window",
        "active": True,
        "tag": str(args.tag or "").strip() or None,
        "started_ts": now,
        "end_ts": end_ts,
        "duration_hours": duration_hours,
        "config_path": str(_config_path()),
        "zone_before": before_zone,
        "zone_after": after_zone,
        "risk_hash_before": risk_hash_before,
        "exit_hash_before": exit_hash_before,
        "baseline_before_window": baseline,
    }
    _write_json(_experiment_path(), experiment)
    print(json.dumps(experiment, indent=2))
    return 0


def cmd_status(_args: argparse.Namespace) -> int:
    now = time.time()
    record = _load_json(_experiment_path(), {})
    if not isinstance(record, dict) or not record:
        print(json.dumps({"active": False, "note": "no experiment record found"}, indent=2))
        return 0

    cfg, decisions, trades = _load_runtime_inputs()
    started_ts = _as_float(record.get("started_ts"), now) or now
    end_ts = _as_float(record.get("end_ts"), now) or now
    partial_after = _window_metrics(
        start_ts=started_ts,
        end_ts=min(now, end_ts),
        decision_rows=decisions,
        trade_rows=trades,
    )
    out = {
        "active": bool(record.get("active")) and end_ts > now,
        "time_remaining_minutes": round(max(end_ts - now, 0.0) / 60.0, 2),
        "zone_before": record.get("zone_before"),
        "zone_after": record.get("zone_after"),
        "current_zone": _current_buy_zone(cfg),
        "partial_after_window": partial_after,
        "baseline_before_window": record.get("baseline_before_window"),
    }
    print(json.dumps(out, indent=2))
    return 0


def _rollback_zone(record: dict[str, Any]) -> list[float]:
    cfg = _load_json(_config_path(), {})
    if not isinstance(cfg, dict):
        cfg = {}
    zone_before = record.get("zone_before")
    if not isinstance(zone_before, list) or len(zone_before) != 2:
        zone_before = [0.05, 0.30]
    cfg.setdefault("market_regime", {})["preferred_buy_zone"] = zone_before
    _write_json(_config_path(), cfg)
    return [float(_as_float(zone_before[0], 0.05) or 0.05), float(_as_float(zone_before[1], 0.30) or 0.30)]


def cmd_finalize(args: argparse.Namespace) -> int:
    now = time.time()
    record = _load_json(_experiment_path(), {})
    if not isinstance(record, dict) or not record:
        raise RuntimeError("No experiment record found.")

    cfg, decisions, trades = _load_runtime_inputs()
    started_ts = _as_float(record.get("started_ts"), now) or now
    end_ts_target = _as_float(record.get("end_ts"), now) or now
    end_ts_effective = min(now, end_ts_target)

    before = record.get("baseline_before_window") or {}
    if not isinstance(before, dict):
        before = {}
    after = _window_metrics(
        start_ts=started_ts,
        end_ts=end_ts_effective,
        decision_rows=decisions,
        trade_rows=trades,
    )
    comparison = _build_comparison(before, after)

    risk_hash_after = _hash_dict(cfg.get("risk"))
    exit_hash_after = _hash_dict(cfg.get("profit_locks"))
    guard = {
        "risk_unchanged": risk_hash_after == record.get("risk_hash_before"),
        "exit_unchanged": exit_hash_after == record.get("exit_hash_before"),
    }

    report = {
        "name": "buy_zone_high_timed_window",
        "generated_ts": now,
        "started_ts": started_ts,
        "ended_ts": end_ts_effective,
        "target_end_ts": end_ts_target,
        "completed_full_window": end_ts_effective >= end_ts_target,
        "zone_before": record.get("zone_before"),
        "zone_after": record.get("zone_after"),
        "before_window": before,
        "after_window": after,
        "comparison": comparison,
        "guard_checks": guard,
    }

    stamp = time.strftime("%Y%m%d-%H%M%S", time.gmtime(now))
    report_json_path = _reports_dir() / f"buy_zone_experiment_report_{stamp}.json"
    report_md_path = _reports_dir() / f"buy_zone_experiment_report_{stamp}.md"
    _write_json(report_json_path, report)
    report_md_path.write_text(
        "\n".join(
            [
                "# Buy-Zone Timed Experiment Report",
                "",
                f"- `zone_before`: `{report['zone_before']}`",
                f"- `zone_after`: `{report['zone_after']}`",
                f"- `completed_full_window`: `{report['completed_full_window']}`",
                "",
                "## Key Metrics (Before -> After)",
                f"- executed_opportunity_rate_pct: `{before.get('executed_opportunity_rate_pct')}` -> `{after.get('executed_opportunity_rate_pct')}`",
                f"- trades_executed: `{before.get('trades_executed')}` -> `{after.get('trades_executed')}`",
                f"- entry_blocked_cycles: `{before.get('entry_blocked_cycles')}` -> `{after.get('entry_blocked_cycles')}`",
                f"- realized_net_pnl_usd: `{before.get('realized_net_pnl_usd')}` -> `{after.get('realized_net_pnl_usd')}`",
                f"- max_drawdown_pct: `{before.get('max_drawdown_pct')}` -> `{after.get('max_drawdown_pct')}`",
                "",
                "## Deltas",
                f"- executed_opportunity_rate_pct_delta: `{comparison.get('executed_opportunity_rate_pct_delta')}`",
                f"- trades_executed_delta: `{comparison.get('trades_executed_delta')}`",
                f"- entry_blocked_cycles_delta: `{comparison.get('entry_blocked_cycles_delta')}`",
                f"- realized_net_pnl_usd_delta: `{comparison.get('realized_net_pnl_usd_delta')}`",
                f"- max_drawdown_pct_delta: `{comparison.get('max_drawdown_pct_delta')}`",
                "",
                "## Guard Checks",
                f"- risk_unchanged: `{guard.get('risk_unchanged')}`",
                f"- exit_unchanged: `{guard.get('exit_unchanged')}`",
            ]
        ),
        encoding="utf-8",
    )

    rolled_back_to = None
    if not bool(args.keep):
        rolled_back_to = _rollback_zone(record)

    record["active"] = False
    record["finalized_ts"] = now
    record["report_json"] = str(report_json_path)
    record["report_md"] = str(report_md_path)
    record["rolled_back_to"] = rolled_back_to
    _write_json(_experiment_path(), record)

    print(
        json.dumps(
            {
                "report_json": str(report_json_path),
                "report_md": str(report_md_path),
                "rolled_back_to": rolled_back_to,
                "comparison": comparison,
                "guard_checks": guard,
            },
            indent=2,
        )
    )
    return 0


def cmd_rollback(_args: argparse.Namespace) -> int:
    record = _load_json(_experiment_path(), {})
    if not isinstance(record, dict) or not record:
        raise RuntimeError("No experiment record found.")
    zone = _rollback_zone(record)
    record["active"] = False
    record["rolled_back_to"] = zone
    record["rollback_ts"] = time.time()
    _write_json(_experiment_path(), record)
    print(json.dumps({"rolled_back_to": zone}, indent=2))
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Timed, reversible buy-zone-high experiment (config-only).")
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_start = sub.add_parser("start", help="Start experiment and apply buy_zone_high.")
    p_start.add_argument("--high", type=float, default=0.50)
    p_start.add_argument("--hours", type=float, default=4.0)
    p_start.add_argument("--tag", default="")

    p_status = sub.add_parser("status", help="Show experiment status and partial after-window metrics.")

    p_finalize = sub.add_parser("finalize", help="Finalize experiment, generate report, rollback unless --keep.")
    p_finalize.add_argument("--keep", action="store_true", help="Keep experiment buy-zone instead of rolling back.")

    p_rollback = sub.add_parser("rollback", help="Rollback buy zone to pre-experiment value.")

    args = parser.parse_args()
    if args.cmd == "start":
        return cmd_start(args)
    if args.cmd == "status":
        return cmd_status(args)
    if args.cmd == "finalize":
        return cmd_finalize(args)
    if args.cmd == "rollback":
        return cmd_rollback(args)
    raise RuntimeError(f"Unsupported command: {args.cmd}")


if __name__ == "__main__":
    raise SystemExit(main())

