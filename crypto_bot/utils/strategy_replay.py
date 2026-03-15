from __future__ import annotations

import copy
import json
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

STRATEGY_STATE_MAPS = (
    "_last_signal",
    "_last_sell_price",
    "_entry_price",
    "_entry_time",
    "_profit_lock",
    "_peak_pnl",
    "_last_momentum",
    "_last_regime",
    "_last_score",
    "_last_volatility",
)


def _load_strategy_engine():
    try:
        from strategy import strategy_engine as se
    except ModuleNotFoundError:
        from crypto_bot.strategy import strategy_engine as se
    return se


def _reset_strategy_globals(se: Any, state_dir: Path):
    for mapping_name in STRATEGY_STATE_MAPS:
        mapping = getattr(se, mapping_name, None)
        if isinstance(mapping, dict):
            mapping.clear()

    state_dir.mkdir(parents=True, exist_ok=True)
    paper_state_path = state_dir / "paper_state.json"
    strategy_state_path = state_dir / "strategy_state.json"
    if not paper_state_path.exists():
        paper_state_path.write_text('{"balance": 10000, "positions": {}}', encoding="utf-8")
    if not strategy_state_path.exists():
        strategy_state_path.write_text("{}", encoding="utf-8")

    se.STRATEGY_STATE_FILE = strategy_state_path
    se.PAPER_STATE_FILE = paper_state_path
    se._synced = True
    se._last_paper_state_mtime = None
    se._metrics_dirty = False
    se._last_metrics_flush_at = 0.0


def _apply_pre_state(se: Any, case: dict):
    pre_state = case.get("pre_state", {})
    if not isinstance(pre_state, dict):
        return

    entries = pre_state.get("entries", [])
    if not isinstance(entries, list):
        return

    for entry in entries:
        if not isinstance(entry, dict):
            continue
        symbol = entry.get("symbol")
        price = entry.get("price")
        if not symbol or price is None:
            continue
        try:
            se.confirm_entry(str(symbol), float(price))
        except Exception:
            continue


def run_replay_cases(cases: list[dict], base_config: dict) -> dict:
    se = _load_strategy_engine()

    results = []
    mismatches = []
    original_save_state = getattr(se, "_save_strategy_state", None)
    replay_logger = getattr(se, "logger", None)
    logger_state = None
    if callable(original_save_state):
        se._save_strategy_state = lambda: None
    if replay_logger is not None:
        logger_state = (
            replay_logger.disabled,
            replay_logger.level,
            replay_logger.propagate,
        )
        replay_logger.disabled = True

    tmp_root = Path(__file__).resolve().parents[2] / ".tmp_replay"
    tmp_root.mkdir(parents=True, exist_ok=True)
    tmp_dir = tmp_root / "work"
    shutil.rmtree(tmp_dir, ignore_errors=True)
    tmp_dir.mkdir(parents=True, exist_ok=True)
    try:
        for index, case in enumerate(cases, start=1):
            case_id = case.get("id") or f"case_{index:04d}"
            snapshot = case.get("snapshot")
            expected = case.get("expected", {})
            if not isinstance(snapshot, dict) or not isinstance(expected, dict):
                mismatches.append(
                    {
                        "id": case_id,
                        "error": "invalid_case_shape",
                    }
                )
                continue

            cfg = copy.deepcopy(base_config)
            override = case.get("config_override")
            if isinstance(override, dict):
                cfg.update(override)

            _reset_strategy_globals(se, tmp_dir)
            _apply_pre_state(se, case)

            try:
                decision = se.generate_decision(copy.deepcopy(snapshot), cfg)
            except Exception as exc:
                mismatches.append(
                    {
                        "id": case_id,
                        "error": f"replay_exception: {exc}",
                    }
                )
                continue

            actual_action = str(decision.get("action", ""))
            actual_reason = str(decision.get("reason", ""))
            expected_action = str(expected.get("action", ""))
            expected_reason = str(expected.get("reason", ""))
            expected_reason_prefix = expected.get("reason_prefix")

            action_match = actual_action == expected_action
            if expected_reason_prefix is not None:
                reason_match = actual_reason.startswith(str(expected_reason_prefix))
            else:
                reason_match = actual_reason == expected_reason
            matched = action_match and reason_match

            result = {
                "id": case_id,
                "symbol": snapshot.get("symbol"),
                "expected": {
                    "action": expected_action,
                    "reason": expected_reason,
                    "reason_prefix": expected_reason_prefix,
                },
                "actual": {
                    "action": actual_action,
                    "reason": actual_reason,
                },
                "matched": matched,
            }
            results.append(result)
            if not matched:
                mismatches.append(result)
    finally:
        if logger_state is not None and replay_logger is not None:
            replay_logger.disabled = logger_state[0]
            replay_logger.setLevel(logger_state[1])
            replay_logger.propagate = logger_state[2]
        if callable(original_save_state):
            se._save_strategy_state = original_save_state
        shutil.rmtree(tmp_dir, ignore_errors=True)

    return {
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "case_count": len(cases),
        "matched_count": len([result for result in results if result["matched"]]),
        "mismatch_count": len(mismatches),
        "mismatches": mismatches,
        "results": results,
    }


def run_replay_fixture(fixture_path: str | Path, output_path: str | Path | None = None) -> dict:
    fixture = Path(fixture_path)
    payload = json.loads(fixture.read_text(encoding="utf-8"))

    if not isinstance(payload, dict):
        raise ValueError(f"Invalid fixture format: {fixture}")

    base_config = payload.get("config", {})
    cases = payload.get("cases", [])
    if not isinstance(base_config, dict):
        raise ValueError("Fixture must contain a dict 'config'")
    if not isinstance(cases, list):
        raise ValueError("Fixture must contain a list 'cases'")

    report = run_replay_cases(cases=cases, base_config=base_config)
    report["fixture_path"] = str(fixture)

    if output_path is not None:
        output = Path(output_path)
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(json.dumps(report, indent=2), encoding="utf-8")

    return report
