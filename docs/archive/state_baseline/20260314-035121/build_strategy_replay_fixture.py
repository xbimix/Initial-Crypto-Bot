from __future__ import annotations

import argparse
import json
import re
import sys
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path


SNAPSHOT_RE = re.compile(r"SNAPSHOT\s+([A-Z0-9-]+)\s+\|\s+(.+)$")
DECISION_RE = re.compile(r"([A-Z0-9-]+)\s*(?:->|→)\s*(BUY|SELL|HOLD)\s*\|\s*reason=(.+)$")
FIELD_RE = re.compile(r"([a-zA-Z0-9_]+)=([^\s]+)")

REASON_SKIP_PREFIXES = (
    "profit_lock_exit_",
    "regime_",
)
REASON_SKIP_EXACT = {
    "waiting_for_first_lock",
    "in_position",
    "desync_protection",
    "structural_break_exit",
    "scalper_in_position",
    "scalper_take_profit",
    "scalper_stop_loss",
    "scalper_vwap_exit",
    "scalper_time_stop",
    "volatility_scalper_entry",
    "bear_market_mean_reversion_buy",
}
REASON_ALLOW_EXACT = {
    "insufficient_data",
    "atr_too_low",
    "price_above_buy_zone",
    "price_below_buy_zone",
    "insufficient_volatility_stretch",
    "score_below_threshold",
    "momentum_still_falling",
}


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[1]


def _to_float(value: str, default: float = 0.0) -> float:
    try:
        return float(value)
    except Exception:
        return default


def _to_int(value: str, default: int = 0) -> int:
    try:
        return int(float(value))
    except Exception:
        return default


def _parse_snapshot(line: str):
    match = SNAPSHOT_RE.search(line)
    if not match:
        return None

    symbol = match.group(1).strip().upper()
    body = match.group(2)
    fields = dict(FIELD_RE.findall(body))
    required = {"price", "mom_norm", "atr_raw", "vwap", "points", "quality", "24h_low", "24h_high", "spread_bps"}
    if not required.issubset(fields.keys()):
        return None

    quality = fields.get("quality", "ok")
    data_quality_ok = quality == "ok"
    points = max(_to_int(fields.get("points", "0"), 0), 0)
    price = _to_float(fields.get("price", "0"), 0.0)
    atr = _to_float(fields.get("atr_raw", "0"), 0.0)
    vwap = _to_float(fields.get("vwap", "0"), 0.0)

    history_points = max(min(points, 60), 1)
    snapshot = {
        "symbol": symbol,
        "price": price,
        "momentum_norm": _to_float(fields.get("mom_norm", "0"), 0.0),
        "trade_count": points if data_quality_ok else 0,
        "high_24h": _to_float(fields.get("24h_high", "0"), 0.0),
        "low_24h": _to_float(fields.get("24h_low", "0"), 0.0),
        "atr": atr,
        "vwap": vwap,
        "rsi": _to_float(fields.get("rsi", "50"), 50.0),
        "spread_bps": _to_float(fields.get("spread_bps", "0"), 0.0),
        "recent_prices": [price for _ in range(history_points)],
        "data_quality_ok": data_quality_ok,
        "data_quality_reason": quality,
    }
    return symbol, snapshot


def _parse_decision(line: str):
    match = DECISION_RE.search(line)
    if not match:
        return None
    symbol = match.group(1).strip().upper()
    action = match.group(2).strip().upper()
    reason = match.group(3).strip()
    return symbol, action, reason


def _reason_allowed(action: str, reason: str) -> bool:
    if action != "HOLD":
        return False

    if reason in REASON_SKIP_EXACT:
        return False

    for prefix in REASON_SKIP_PREFIXES:
        if reason.startswith(prefix):
            return False

    if "warming_up_history" in reason:
        return True

    return reason in REASON_ALLOW_EXACT


def _stable_case_id(symbol: str, reason: str, index: int) -> str:
    normalized_reason = re.sub(r"[^a-z0-9]+", "_", reason.lower()).strip("_")
    return f"log_replay_{index:04d}_{symbol.lower()}_{normalized_reason}"


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Build replay fixture from existing bot logs.",
    )
    parser.add_argument(
        "--log",
        action="append",
        default=[],
        help="Path to bot log file (can be used multiple times)",
    )
    parser.add_argument(
        "--config",
        default=str(_repo_root() / "crypto_bot" / "state" / "config.json"),
        help="Path to baseline config JSON",
    )
    parser.add_argument(
        "--output",
        default=str(
            _repo_root()
            / "crypto_bot"
            / "tests"
            / "fixtures"
            / "strategy_replay_cases.json"
        ),
        help="Output fixture path",
    )
    parser.add_argument(
        "--max-cases",
        type=int,
        default=80,
        help="Maximum number of replay cases to emit",
    )
    parser.add_argument(
        "--max-candidates",
        type=int,
        default=1200,
        help="Maximum extracted candidates before validation",
    )
    parser.add_argument(
        "--scan-lines-per-log",
        type=int,
        default=25000,
        help="Only scan the last N lines per log (0 means full file)",
    )
    parser.add_argument(
        "--max-pre-per-reason",
        type=int,
        default=120,
        help="Pre-validation cap per reason to avoid huge candidate pools",
    )
    parser.add_argument(
        "--max-per-reason",
        type=int,
        default=12,
        help="Maximum cases kept for each reason",
    )
    args = parser.parse_args()

    repo_root = _repo_root()
    if not args.log:
        args.log = [
            str(repo_root / "crypto_bot" / "state" / "bot.log.1"),
            str(repo_root / "crypto_bot" / "state" / "bot.log"),
        ]

    log_paths = [Path(path) for path in args.log]
    config_path = Path(args.config)
    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    config = json.loads(config_path.read_text(encoding="utf-8"))
    if not isinstance(config, dict):
        raise ValueError(f"Config must be JSON object: {config_path}")

    crypto_bot_root = repo_root / "crypto_bot"
    if str(crypto_bot_root) not in sys.path:
        sys.path.insert(0, str(crypto_bot_root))
    from utils.strategy_replay import run_replay_cases

    last_snapshot_by_symbol = {}
    candidates = []
    seen = set()
    pre_reason_counts = defaultdict(int)
    max_candidates = max(int(args.max_candidates), 1)
    scan_lines_per_log = max(int(args.scan_lines_per_log), 0)
    max_pre_per_reason = max(int(args.max_pre_per_reason), 1)

    for log_path in log_paths:
        if not log_path.exists():
            continue
        lines = log_path.read_text(encoding="utf-8", errors="replace").splitlines()
        if scan_lines_per_log > 0 and len(lines) > scan_lines_per_log:
            lines = lines[-scan_lines_per_log:]

        print(f"Scanning {log_path} ({len(lines)} lines)")
        for raw_line in lines:
            parsed_snapshot = _parse_snapshot(raw_line)
            if parsed_snapshot is not None:
                symbol, snapshot = parsed_snapshot
                last_snapshot_by_symbol[symbol] = snapshot
                continue

            parsed_decision = _parse_decision(raw_line)
            if parsed_decision is None:
                continue

            symbol, action, reason = parsed_decision
            snapshot = last_snapshot_by_symbol.get(symbol)
            if snapshot is None:
                continue
            if not _reason_allowed(action, reason):
                continue

            if pre_reason_counts[reason] >= max_pre_per_reason:
                continue

            key = (
                symbol,
                action,
                reason,
                round(float(snapshot.get("price", 0.0)), 8),
                int(snapshot.get("trade_count", 0)),
            )
            if key in seen:
                continue
            seen.add(key)

            pre_reason_counts[reason] += 1
            candidates.append(
                {
                    "id": _stable_case_id(symbol=symbol, reason=reason, index=len(candidates) + 1),
                    "snapshot": snapshot,
                    "expected": {
                        "action": action,
                        "reason": reason,
                    },
                }
            )
            if len(candidates) % 200 == 0:
                print(f"Collected candidates: {len(candidates)}")
            if len(candidates) >= max_candidates:
                break
        if len(candidates) >= max_candidates:
            break

    if not candidates:
        raise RuntimeError("No replay candidates were extracted from the provided logs.")

    print(f"Validating {len(candidates)} replay candidates...")
    validation = run_replay_cases(cases=candidates, base_config=config)
    matched_ids = {
        item.get("id")
        for item in validation.get("results", [])
        if item.get("matched")
    }
    stable_cases = [case for case in candidates if case.get("id") in matched_ids]

    by_reason = defaultdict(int)
    final_cases = []
    for case in stable_cases:
        reason = str(case.get("expected", {}).get("reason", ""))
        if by_reason[reason] >= max(int(args.max_per_reason), 1):
            continue
        by_reason[reason] += 1
        final_cases.append(case)
        if len(final_cases) >= max(int(args.max_cases), 1):
            break

    if not final_cases:
        raise RuntimeError(
            "No stable replay cases remained after validation. "
            "Try different logs or loosen candidate filters."
        )

    payload = {
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "source": {
            "logs": [str(path) for path in log_paths if path.exists()],
            "config": str(config_path),
            "candidate_count": len(candidates),
            "stable_count": len(stable_cases),
            "selected_count": len(final_cases),
        },
        "config": config,
        "cases": final_cases,
    }
    output_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")

    print(
        json.dumps(
            {
                "output": str(output_path),
                "candidate_count": len(candidates),
                "stable_count": len(stable_cases),
                "selected_count": len(final_cases),
                "reason_counts": dict(by_reason),
            },
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
