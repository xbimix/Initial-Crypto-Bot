from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import sqlite3
import sys
import time
from collections import Counter
from pathlib import Path
from typing import Any

try:
    from crypto_bot.utils.state_paths import project_root, resolve_state_dir
except ImportError:
    if __package__ in {None, ""}:
        sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from utils.state_paths import project_root, resolve_state_dir

EXIT_HOLD_REASONS = {
    "waiting_for_first_lock",
    "in_position",
    "scalper_in_position",
}

CANARY_DEFS: dict[str, dict[str, Any]] = {
    "A": {
        "label": "price_zone_participation",
        "target_reason": "price_above_buy_zone",
        "help": "Increase MR buy-zone high slightly.",
    },
    "B": {
        "label": "score_selectivity",
        "target_reason": "score_below_threshold",
        "help": "Lower score threshold slightly.",
    },
    "C": {
        "label": "stretch_strictness",
        "target_reason": "insufficient_volatility_stretch",
        "help": "Relax MR stretch threshold slightly.",
    },
}


def _state_dir() -> Path:
    return resolve_state_dir(project_root() / "crypto_bot" / "state")


def _config_path() -> Path:
    return _state_dir() / "config.json"


def _decision_audit_path() -> Path:
    return _state_dir() / "decision_audit.jsonl"


def _trades_path() -> Path:
    return _state_dir() / "trades.json"


def _sync_health_path() -> Path:
    return _state_dir() / "market_sync_health.json"


def _db_path() -> Path:
    return _state_dir() / "market_data.db"


def _experiment_path() -> Path:
    path = _state_dir() / "experiments" / "critical_strategy_canary.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


def _backup_dir() -> Path:
    path = _state_dir() / "experiments" / "backups"
    path.mkdir(parents=True, exist_ok=True)
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
        return json.loads(path.read_text(encoding="utf-8-sig"))
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


def _hash_dict(value: dict[str, Any] | None) -> str:
    payload = value if isinstance(value, dict) else {}
    text = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


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
    execution_attempts = sum(
        1 for row in scoped_decisions if str(row.get("action") or "").strip().upper() in {"BUY", "SELL"}
    )
    blocked_rows = [row for row in scoped_decisions if not bool(row.get("executed", False))]
    exit_hold_rows = [row for row in blocked_rows if _reason(row) in EXIT_HOLD_REASONS]
    entry_blocked_rows = [row for row in blocked_rows if _reason(row) not in EXIT_HOLD_REASONS]
    entry_opportunities = executed + len(entry_blocked_rows)
    executed_opportunity_rate_pct = (
        (executed / max(entry_opportunities, 1)) * 100.0 if entry_opportunities > 0 else 0.0
    )

    reason_counts: Counter[str] = Counter(_reason(row) for row in scoped_decisions)
    reason_pct_total = {
        reason: round((count / max(total_cycles, 1)) * 100.0, 4)
        for reason, count in reason_counts.items()
    }

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
    if balances:
        peak = balances[0]
        max_dd_pct = 0.0
        for value in balances:
            if value > peak:
                peak = value
                continue
            dd_usd = max(peak - value, 0.0)
            dd_pct = (dd_usd / peak * 100.0) if peak > 0 else 0.0
            if dd_pct > max_dd_pct:
                max_dd_pct = dd_pct
        max_drawdown_pct = round(max_dd_pct, 4)

    return {
        "window_start_ts": float(start_ts),
        "window_end_ts": float(end_ts),
        "window_hours": round((end_ts - start_ts) / 3600.0, 4),
        "total_cycles": int(total_cycles),
        "trades_executed": int(executed),
        "execution_attempts": int(execution_attempts),
        "entry_blocked_cycles": int(len(entry_blocked_rows)),
        "exit_hold_cycles": int(len(exit_hold_rows)),
        "entry_opportunities": int(entry_opportunities),
        "executed_opportunity_rate_pct": round(executed_opportunity_rate_pct, 4),
        "rejection_mix_top": top_rejections,
        "reason_counts": {k: int(v) for k, v in reason_counts.items()},
        "reason_pct_total": reason_pct_total,
        "realized_net_pnl_usd": round(realized_net_pnl_usd, 6),
        "max_drawdown_pct": max_drawdown_pct,
    }


def _current_canary_values(cfg: dict[str, Any]) -> dict[str, float]:
    regime = cfg.get("market_regime")
    if not isinstance(regime, dict):
        regime = {}
        cfg["market_regime"] = regime
    scalper = cfg.get("volatility_scalper")
    if not isinstance(scalper, dict):
        scalper = {}
        cfg["volatility_scalper"] = scalper
    preferred = regime.get("preferred_buy_zone")
    if not isinstance(preferred, list) or len(preferred) < 2:
        preferred = [-0.1, 0.5]
        regime["preferred_buy_zone"] = preferred
    return {
        "market_regime.preferred_buy_zone.low": float(_as_float(preferred[0], -0.1) or -0.1),
        "market_regime.preferred_buy_zone.high": float(_as_float(preferred[1], 0.5) or 0.5),
        "market_regime.min_score_to_buy": float(_as_float(regime.get("min_score_to_buy"), 45.0) or 45.0),
        "min_score_to_buy": float(_as_float(cfg.get("min_score_to_buy"), 45.0) or 45.0),
        "volatility_scalper.min_score_to_buy": float(_as_float(scalper.get("min_score_to_buy"), 45.0) or 45.0),
        "market_regime.min_z_score": float(_as_float(regime.get("min_z_score"), -1.3) or -1.3),
    }


def _apply_canary_update(cfg: dict[str, Any], canary: str, target_value: float | None = None) -> tuple[dict[str, float], dict[str, float]]:
    canary = str(canary or "").strip().upper()
    if canary not in CANARY_DEFS:
        raise ValueError(f"Unsupported canary: {canary}")
    before = _current_canary_values(cfg)
    regime = cfg.setdefault("market_regime", {})
    scalper = cfg.setdefault("volatility_scalper", {})
    if not isinstance(regime, dict):
        raise ValueError("market_regime must be an object")
    if not isinstance(scalper, dict):
        raise ValueError("volatility_scalper must be an object")

    if canary == "A":
        preferred = regime.get("preferred_buy_zone")
        if not isinstance(preferred, list) or len(preferred) < 2:
            preferred = [before["market_regime.preferred_buy_zone.low"], before["market_regime.preferred_buy_zone.high"]]
        high = float(target_value) if target_value is not None else 0.55
        preferred[0] = float(_as_float(preferred[0], before["market_regime.preferred_buy_zone.low"]) or before["market_regime.preferred_buy_zone.low"])
        preferred[1] = high
        regime["preferred_buy_zone"] = preferred
    elif canary == "B":
        value = float(target_value) if target_value is not None else 43.0
        regime["min_score_to_buy"] = value
        cfg["min_score_to_buy"] = value
        scalper["min_score_to_buy"] = value
    elif canary == "C":
        value = float(target_value) if target_value is not None else -1.1
        regime["min_z_score"] = value

    after = _current_canary_values(cfg)
    return before, after


def _rollback_from_backup(record: dict[str, Any]) -> dict[str, float]:
    backup_path = Path(str(record.get("config_backup_path") or ""))
    if not backup_path.exists():
        raise RuntimeError("Config backup path missing for rollback")
    shutil.copy2(backup_path, _config_path())
    cfg = _load_json(_config_path(), {})
    if not isinstance(cfg, dict):
        cfg = {}
    return _current_canary_values(cfg)


def _db_integrity_snapshot() -> dict[str, Any]:
    db_path = _db_path()
    if not db_path.exists():
        return {
            "db_exists": False,
            "db_null_close_time": None,
            "db_duplicate_primary_rows": None,
        }
    conn = sqlite3.connect(db_path)
    try:
        cur = conn.cursor()
        null_close = cur.execute("select count(*) from candles where close_time is null").fetchone()[0]
        dupes = cur.execute(
            "select count(*) from (select symbol,timeframe,open_time,count(*) c from candles group by symbol,timeframe,open_time having c>1)"
        ).fetchone()[0]
    finally:
        conn.close()
    return {
        "db_exists": True,
        "db_null_close_time": int(null_close),
        "db_duplicate_primary_rows": int(dupes),
    }


def _slo_snapshot(sync_health: dict[str, Any]) -> dict[str, Any]:
    slo = sync_health.get("slo", {}) if isinstance(sync_health, dict) else {}
    if not isinstance(slo, dict):
        slo = {}
    ing = sync_health.get("ingestion_freshness", {}) if isinstance(sync_health, dict) else {}
    if not isinstance(ing, dict):
        ing = {}
    return {
        "slo_status": str(slo.get("status") or "").upper() or None,
        "decision_freshness_ok": bool(slo.get("decision_freshness_ok", False)),
        "quality_ok": bool(slo.get("quality_ok", False)),
        "throughput_ok": bool(slo.get("throughput_ok", False)),
        "entry_block_reason": slo.get("entry_block_reason"),
        "stale_ratio_pct": _as_float(ing.get("stale_ratio_pct")),
    }


def _build_comparison(before: dict[str, Any], after: dict[str, Any], target_reason: str) -> dict[str, Any]:
    def _delta(key: str) -> float | None:
        a = _as_float(after.get(key))
        b = _as_float(before.get(key))
        if a is None or b is None:
            return None
        return round(a - b, 6)

    reason_key = str(target_reason or "").strip()
    before_share = _as_float((before.get("reason_pct_total") or {}).get(reason_key), 0.0) or 0.0
    after_share = _as_float((after.get("reason_pct_total") or {}).get(reason_key), 0.0) or 0.0

    return {
        "execution_attempts_delta": _delta("execution_attempts"),
        "executed_opportunity_rate_pct_delta": _delta("executed_opportunity_rate_pct"),
        "trades_executed_delta": _delta("trades_executed"),
        "entry_blocked_cycles_delta": _delta("entry_blocked_cycles"),
        "realized_net_pnl_usd_delta": _delta("realized_net_pnl_usd"),
        "max_drawdown_pct_delta": _delta("max_drawdown_pct"),
        "target_reason": reason_key,
        "target_reason_share_before_pct": round(before_share, 4),
        "target_reason_share_after_pct": round(after_share, 4),
        "target_reason_share_delta_pct": round(after_share - before_share, 4),
    }


def _build_promotion_checks(
    *,
    comparison: dict[str, Any],
    guard_checks: dict[str, Any],
    slo_snapshot: dict[str, Any],
    db_snapshot: dict[str, Any],
) -> dict[str, Any]:
    drawdown_delta = _as_float(comparison.get("max_drawdown_pct_delta"))
    if drawdown_delta is None:
        drawdown_not_worse = True
    else:
        drawdown_not_worse = drawdown_delta <= 0.0

    freshness_green = (
        str(slo_snapshot.get("slo_status") or "").upper() == "OK"
        and bool(slo_snapshot.get("decision_freshness_ok"))
        and bool(slo_snapshot.get("quality_ok"))
        and bool(slo_snapshot.get("throughput_ok"))
        and int(db_snapshot.get("db_null_close_time") or 0) == 0
        and int(db_snapshot.get("db_duplicate_primary_rows") or 0) == 0
    )

    checks = {
        "execution_attempts_up": (_as_float(comparison.get("execution_attempts_delta"), 0.0) or 0.0) > 0.0,
        "drawdown_not_worse": drawdown_not_worse,
        "rejection_mix_improved": (_as_float(comparison.get("target_reason_share_delta_pct"), 0.0) or 0.0) < 0.0,
        "risk_unchanged": bool(guard_checks.get("risk_unchanged")),
        "paper_execution_unchanged": bool(guard_checks.get("paper_execution_unchanged")),
        "exit_unchanged": bool(guard_checks.get("exit_unchanged")),
        "freshness_data_green": freshness_green,
    }
    checks["all_pass"] = all(bool(v) for v in checks.values())
    return checks


def _load_runtime_inputs() -> tuple[dict[str, Any], list[dict[str, Any]], list[dict[str, Any]], dict[str, Any]]:
    cfg = _load_json(_config_path(), {})
    if not isinstance(cfg, dict):
        raise ValueError(f"Invalid config payload at {_config_path()}")
    decisions = _load_jsonl(_decision_audit_path())
    trades = _load_json(_trades_path(), [])
    if not isinstance(trades, list):
        trades = []
    sync_health = _load_json(_sync_health_path(), {})
    if not isinstance(sync_health, dict):
        sync_health = {}
    return cfg, decisions, trades, sync_health


def cmd_start(args: argparse.Namespace) -> int:
    now = time.time()
    canary = str(args.canary).strip().upper()
    if canary not in CANARY_DEFS:
        raise RuntimeError(f"Unsupported canary '{canary}'. Use one of: {', '.join(sorted(CANARY_DEFS))}")
    duration_hours = max(float(args.hours), 0.25)
    end_ts = now + duration_hours * 3600.0
    target_value = _as_float(args.value)

    record = _load_json(_experiment_path(), {})
    if isinstance(record, dict) and bool(record.get("active")) and (_as_float(record.get("end_ts"), 0.0) or 0.0) > now:
        raise RuntimeError("A critical strategy canary is already active. Finalize or rollback first.")

    cfg, decisions, trades, sync_health = _load_runtime_inputs()
    stamp = time.strftime("%Y%m%d-%H%M%S", time.gmtime(now))
    backup_path = _backup_dir() / f"config_canary_{stamp}.json"
    shutil.copy2(_config_path(), backup_path)

    before_values, after_values = _apply_canary_update(cfg, canary, target_value=target_value)
    invariant_hashes = {
        "risk_hash_before": _hash_dict(cfg.get("risk")),
        "paper_execution_hash_before": _hash_dict(cfg.get("paper_execution")),
        "exit_hash_before": _hash_dict(cfg.get("profit_locks")),
    }
    _write_json(_config_path(), cfg)

    baseline = _window_metrics(
        start_ts=now - duration_hours * 3600.0,
        end_ts=now,
        decision_rows=decisions,
        trade_rows=trades,
    )

    experiment = {
        "name": "critical_strategy_canary",
        "active": True,
        "canary": canary,
        "canary_label": CANARY_DEFS[canary]["label"],
        "target_reason": CANARY_DEFS[canary]["target_reason"],
        "tag": str(args.tag or "").strip() or None,
        "started_ts": now,
        "end_ts": end_ts,
        "duration_hours": duration_hours,
        "target_value": target_value,
        "config_path": str(_config_path()),
        "config_backup_path": str(backup_path),
        "values_before": before_values,
        "values_after": after_values,
        **invariant_hashes,
        "baseline_before_window": baseline,
        "baseline_slo": _slo_snapshot(sync_health),
        "baseline_db": _db_integrity_snapshot(),
    }
    _write_json(_experiment_path(), experiment)
    print(json.dumps(experiment, indent=2))
    return 0


def cmd_status(_args: argparse.Namespace) -> int:
    now = time.time()
    record = _load_json(_experiment_path(), {})
    if not isinstance(record, dict) or not record:
        print(json.dumps({"active": False, "note": "no canary record found"}, indent=2))
        return 0

    cfg, decisions, trades, sync_health = _load_runtime_inputs()
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
        "canary": record.get("canary"),
        "canary_label": record.get("canary_label"),
        "time_remaining_minutes": round(max(end_ts - now, 0.0) / 60.0, 2),
        "values_before": record.get("values_before"),
        "values_after": record.get("values_after"),
        "current_values": _current_canary_values(cfg),
        "partial_after_window": partial_after,
        "baseline_before_window": record.get("baseline_before_window"),
        "current_slo": _slo_snapshot(sync_health),
        "current_db": _db_integrity_snapshot(),
    }
    print(json.dumps(out, indent=2))
    return 0


def cmd_finalize(args: argparse.Namespace) -> int:
    now = time.time()
    record = _load_json(_experiment_path(), {})
    if not isinstance(record, dict) or not record:
        raise RuntimeError("No canary record found.")

    cfg, decisions, trades, sync_health = _load_runtime_inputs()
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
    target_reason = str(record.get("target_reason") or "")
    comparison = _build_comparison(before, after, target_reason=target_reason)

    guard = {
        "risk_unchanged": _hash_dict(cfg.get("risk")) == record.get("risk_hash_before"),
        "paper_execution_unchanged": _hash_dict(cfg.get("paper_execution")) == record.get("paper_execution_hash_before"),
        "exit_unchanged": _hash_dict(cfg.get("profit_locks")) == record.get("exit_hash_before"),
    }
    slo_now = _slo_snapshot(sync_health)
    db_now = _db_integrity_snapshot()
    promotion = _build_promotion_checks(
        comparison=comparison,
        guard_checks=guard,
        slo_snapshot=slo_now,
        db_snapshot=db_now,
    )

    report = {
        "name": "critical_strategy_canary",
        "generated_ts": now,
        "canary": record.get("canary"),
        "canary_label": record.get("canary_label"),
        "target_reason": target_reason,
        "started_ts": started_ts,
        "ended_ts": end_ts_effective,
        "target_end_ts": end_ts_target,
        "completed_full_window": end_ts_effective >= end_ts_target,
        "values_before": record.get("values_before"),
        "values_after": record.get("values_after"),
        "before_window": before,
        "after_window": after,
        "comparison": comparison,
        "guard_checks": guard,
        "slo_now": slo_now,
        "db_now": db_now,
        "promotion_checks": promotion,
    }

    stamp = time.strftime("%Y%m%d-%H%M%S", time.gmtime(now))
    canary_key = str(record.get("canary") or "X").upper()
    report_json_path = _reports_dir() / f"critical_canary_{canary_key}_report_{stamp}.json"
    report_md_path = _reports_dir() / f"critical_canary_{canary_key}_report_{stamp}.md"
    _write_json(report_json_path, report)
    report_md_path.write_text(
        "\n".join(
            [
                f"# Critical Strategy Canary {canary_key} Report",
                "",
                f"- `canary_label`: `{report.get('canary_label')}`",
                f"- `target_reason`: `{target_reason}`",
                f"- `completed_full_window`: `{report.get('completed_full_window')}`",
                "",
                "## Key Metrics (Before -> After)",
                f"- execution_attempts: `{before.get('execution_attempts')}` -> `{after.get('execution_attempts')}`",
                f"- executed_opportunity_rate_pct: `{before.get('executed_opportunity_rate_pct')}` -> `{after.get('executed_opportunity_rate_pct')}`",
                f"- trades_executed: `{before.get('trades_executed')}` -> `{after.get('trades_executed')}`",
                f"- entry_blocked_cycles: `{before.get('entry_blocked_cycles')}` -> `{after.get('entry_blocked_cycles')}`",
                f"- target_reason_share_pct: `{comparison.get('target_reason_share_before_pct')}` -> `{comparison.get('target_reason_share_after_pct')}`",
                f"- realized_net_pnl_usd: `{before.get('realized_net_pnl_usd')}` -> `{after.get('realized_net_pnl_usd')}`",
                f"- max_drawdown_pct: `{before.get('max_drawdown_pct')}` -> `{after.get('max_drawdown_pct')}`",
                "",
                "## Promotion Checks",
                f"- execution_attempts_up: `{promotion.get('execution_attempts_up')}`",
                f"- drawdown_not_worse: `{promotion.get('drawdown_not_worse')}`",
                f"- rejection_mix_improved: `{promotion.get('rejection_mix_improved')}`",
                f"- risk_unchanged: `{promotion.get('risk_unchanged')}`",
                f"- paper_execution_unchanged: `{promotion.get('paper_execution_unchanged')}`",
                f"- exit_unchanged: `{promotion.get('exit_unchanged')}`",
                f"- freshness_data_green: `{promotion.get('freshness_data_green')}`",
                f"- all_pass: `{promotion.get('all_pass')}`",
            ]
        ),
        encoding="utf-8",
    )

    rolled_back_to = None
    if not bool(args.keep):
        rolled_back_to = _rollback_from_backup(record)

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
                "promotion_checks": promotion,
            },
            indent=2,
        )
    )
    return 0


def cmd_rollback(_args: argparse.Namespace) -> int:
    record = _load_json(_experiment_path(), {})
    if not isinstance(record, dict) or not record:
        raise RuntimeError("No canary record found.")
    values = _rollback_from_backup(record)
    record["active"] = False
    record["rolled_back_to"] = values
    record["rollback_ts"] = time.time()
    _write_json(_experiment_path(), record)
    print(json.dumps({"rolled_back_to": values}, indent=2))
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Staged critical strategy canary (A/B/C) with invariant guards and rollback."
    )
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_start = sub.add_parser("start", help="Start canary A/B/C and apply a single config knob.")
    p_start.add_argument("--canary", required=True, choices=sorted(CANARY_DEFS.keys()))
    p_start.add_argument("--hours", type=float, default=4.0)
    p_start.add_argument("--value", type=float, default=None, help="Optional override target value for chosen canary.")
    p_start.add_argument("--tag", default="")

    sub.add_parser("status", help="Show active canary status with partial metrics.")

    p_finalize = sub.add_parser("finalize", help="Finalize canary, emit report, rollback unless --keep.")
    p_finalize.add_argument("--keep", action="store_true", help="Keep canary config if promotion checks pass.")

    sub.add_parser("rollback", help="Rollback immediately from saved config backup.")

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
