from __future__ import annotations

import argparse
import json
import statistics
import sys
import time
from collections import Counter
from pathlib import Path
from typing import Any

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from utils.state_paths import project_root, resolve_state_dir


ADVISORY_ONLY_REASONS = {
    "insufficient_advisory",
    "volatility_insufficient",
}


def _as_float(value: Any) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _load_jsonl_rows(path: Path) -> list[dict[str, Any]]:
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


def _is_advisory_only_reason(reason: str) -> bool:
    token = str(reason or "").strip().lower()
    if not token:
        return False
    if token in ADVISORY_ONLY_REASONS:
        return True
    return token.startswith("advisory_")


def _infer_gate_fields(*, reason: str, row: dict[str, Any]) -> tuple[str | None, float | None, float | None, bool | None]:
    condition = str(row.get("gate_trigger_condition") or "").strip() or None
    threshold = _as_float(row.get("gate_trigger_threshold"))
    actual = _as_float(row.get("gate_trigger_actual"))
    correct_raw = row.get("gate_trigger_correct")
    correct = bool(correct_raw) if isinstance(correct_raw, bool) else None
    if condition is not None:
        return condition, threshold, actual, correct

    if reason == "insufficient_data":
        atr = _as_float(row.get("atr_raw"))
        return "atr_raw > 0", 0.0, atr, (atr is None or atr <= 0.0)
    if reason.startswith("market_data_quality:stale"):
        candle_age = _as_float(row.get("candle_age_seconds"))
        stale_after = _as_float(row.get("candle_stale_after_seconds"))
        is_correct = None
        if candle_age is not None and stale_after is not None:
            is_correct = candle_age > stale_after
        return "candle_age_seconds > candle_stale_after_seconds", stale_after, candle_age, is_correct
    if reason == "atr_too_low":
        atr = _as_float(row.get("atr_raw"))
        return "atr_raw >= min_atr", None, atr, (atr is not None and atr > 0.0)
    return None, None, None, None


def _top_reason_detail(reason: str, reason_rows: list[dict[str, Any]]) -> dict[str, Any]:
    condition_counter: Counter[str] = Counter()
    threshold_values: list[float] = []
    actual_values: list[float] = []
    correct_values: list[bool] = []

    for row in reason_rows:
        condition, threshold, actual, correct = _infer_gate_fields(reason=reason, row=row)
        if condition:
            condition_counter[condition] += 1
        if threshold is not None:
            threshold_values.append(threshold)
        if actual is not None:
            actual_values.append(actual)
        if isinstance(correct, bool):
            correct_values.append(correct)

    condition = condition_counter.most_common(1)[0][0] if condition_counter else None
    threshold = statistics.median(threshold_values) if threshold_values else None
    actual = statistics.median(actual_values) if actual_values else None
    correct_rate = (
        (sum(1 for value in correct_values if value) / len(correct_values)) * 100.0
        if correct_values
        else None
    )
    return {
        "condition": condition,
        "threshold_median": threshold,
        "actual_median": actual,
        "actual_min": min(actual_values) if actual_values else None,
        "actual_max": max(actual_values) if actual_values else None,
        "decision_correct_rate_pct": round(correct_rate, 2) if correct_rate is not None else None,
    }


def run_audit(*, hours: int, limit: int = 5) -> dict[str, Any]:
    state_dir = resolve_state_dir(project_root() / "crypto_bot" / "state")
    path = state_dir / "decision_audit.jsonl"
    rows = _load_jsonl_rows(path)
    now = time.time()
    from_ts = now - (max(int(hours), 1) * 3600)

    scoped: list[dict[str, Any]] = []
    for row in rows:
        ts = _as_float(row.get("ts_epoch"))
        if ts is None or ts < from_ts:
            continue
        scoped.append(row)

    total_cycles = len(scoped)
    trades_executed = sum(1 for row in scoped if bool(row.get("executed", False)))
    blocked_cycles = max(total_cycles - trades_executed, 0)

    reason_counts: Counter[str] = Counter(_reason(row) for row in scoped)
    top_reasons: list[dict[str, Any]] = []
    advisory_only_blocked_cycles = 0
    for name, count in reason_counts.most_common(max(limit, 1)):
        pct = (count / total_cycles * 100.0) if total_cycles > 0 else 0.0
        advisory_only = _is_advisory_only_reason(name)
        if name != "executed" and advisory_only:
            advisory_only_blocked_cycles += int(count)
        top_reasons.append(
            {
                "reason": name,
                "count": int(count),
                "pct": round(pct, 2),
                "advisory_only": advisory_only,
                "execution_blocking": (name != "executed") and (not advisory_only),
            }
        )

    execution_blocked_cycles = max(blocked_cycles - advisory_only_blocked_cycles, 0)

    top_reason_detail: dict[str, Any] | None = None
    if top_reasons:
        top_reason = top_reasons[0]["reason"]
        top_rows = [row for row in scoped if _reason(row) == top_reason]
        top_reason_detail = {"reason": top_reason, "rows": len(top_rows)}
        top_reason_detail.update(_top_reason_detail(top_reason, top_rows))

    return {
        "window_hours": int(hours),
        "state_path": str(path),
        "total_cycles": int(total_cycles),
        "trades_executed": int(trades_executed),
        "blocked_cycles": int(blocked_cycles),
        "execution_blocked_cycles": int(execution_blocked_cycles),
        "advisory_only_blocked_cycles": int(advisory_only_blocked_cycles),
        "top_block_reasons": top_reasons,
        "top_reason_detail": top_reason_detail,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Decision trace audit from decision_audit.jsonl.")
    parser.add_argument("--hours", type=int, default=24, help="Lookback window in hours.")
    parser.add_argument("--top", type=int, default=5, help="Number of top reasons to return.")
    args = parser.parse_args()
    report = run_audit(hours=args.hours, limit=args.top)
    print(json.dumps(report, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
