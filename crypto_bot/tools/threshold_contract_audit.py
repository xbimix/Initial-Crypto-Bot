from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path
from typing import Any

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from utils.state_paths import project_root, resolve_state_dir


def _state_dir() -> Path:
    return resolve_state_dir(project_root() / "crypto_bot" / "state")


def _as_float(value: Any, default: float | None = None) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _load_json(path: Path, default: Any) -> Any:
    if not path.exists():
        return default
    return json.loads(path.read_text(encoding="utf-8-sig"))


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


def _normalize_route(value: Any) -> str:
    text = str(value or "").strip().lower()
    if "scalp" in text:
        return "volatility_scalper"
    if "trend" in text:
        return "trend_pullback"
    if "breakout" in text:
        return "breakout_momentum"
    return "mean_reversion"


def _extract_route(row: dict[str, Any]) -> str:
    for key in (
        "buy_route_name",
        "effective_route",
        "effective_strategy",
        "entry_route",
        "route_name",
    ):
        value = row.get(key)
        if value is None:
            continue
        text = str(value).strip()
        if text:
            return _normalize_route(text)
    return "mean_reversion"


def _expected_score_threshold(cfg: dict[str, Any], route: str) -> float:
    regime = cfg.get("market_regime")
    if not isinstance(regime, dict):
        regime = {}
    score_default = _as_float(regime.get("min_score_to_buy"), _as_float(cfg.get("min_score_to_buy"), 60.0))
    if score_default is None:
        score_default = 60.0
    if route == "volatility_scalper":
        scalper = cfg.get("volatility_scalper")
        if not isinstance(scalper, dict):
            scalper = {}
        return float(_as_float(scalper.get("min_score_to_buy"), score_default) or score_default)
    return float(score_default)


def _expected_zscore_threshold(cfg: dict[str, Any], route: str) -> float:
    regime = cfg.get("market_regime")
    if not isinstance(regime, dict):
        regime = {}
    z_default = _as_float(regime.get("min_z_score"), -1.5)
    if z_default is None:
        z_default = -1.5
    if route == "volatility_scalper":
        scalper = cfg.get("volatility_scalper")
        if not isinstance(scalper, dict):
            scalper = {}
        return float(_as_float(scalper.get("entry_z_score_max"), -0.1) or -0.1)
    return float(z_default)


def _is_buy_eval_row(row: dict[str, Any]) -> bool:
    if row.get("buy_route_name") is not None:
        return True
    if row.get("buy_score_threshold") is not None:
        return True
    if row.get("buy_score_actual") is not None:
        return True
    action = str(row.get("action") or "").strip().upper()
    if action in {"BUY", "HOLD"} and row.get("symbol") is not None:
        return True
    return False


def build_threshold_contract_report(
    *,
    cfg: dict[str, Any],
    rows: list[dict[str, Any]],
    start_ts: float,
    end_ts: float,
    tolerance: float = 1e-6,
) -> dict[str, Any]:
    scoped: list[dict[str, Any]] = []
    for row in rows:
        ts = _as_float(row.get("ts_epoch"))
        if ts is None:
            continue
        if ts < start_ts or ts > end_ts:
            continue
        if not _is_buy_eval_row(row):
            continue
        scoped.append(row)

    totals: dict[str, Any] = {
        "total_buy_eval_rows": int(len(scoped)),
        "buy_score_actual_populated": 0,
        "buy_score_threshold_populated": 0,
        "buy_zscore_threshold_populated": 0,
        "buy_score_threshold_mismatch": 0,
        "buy_zscore_threshold_mismatch": 0,
    }
    by_route: dict[str, dict[str, Any]] = {}

    for row in scoped:
        route = _extract_route(row)
        bucket = by_route.setdefault(
            route,
            {
                "count": 0,
                "score_threshold_populated": 0,
                "zscore_threshold_populated": 0,
                "score_threshold_mismatch": 0,
                "zscore_threshold_mismatch": 0,
                "score_actual_populated": 0,
            },
        )
        bucket["count"] += 1

        expected_score = _expected_score_threshold(cfg, route)
        expected_z = _expected_zscore_threshold(cfg, route)

        score_actual = _as_float(row.get("buy_score_actual"))
        if score_actual is not None:
            totals["buy_score_actual_populated"] += 1
            bucket["score_actual_populated"] += 1

        score_threshold = _as_float(row.get("buy_score_threshold"))
        if score_threshold is not None:
            totals["buy_score_threshold_populated"] += 1
            bucket["score_threshold_populated"] += 1
            if abs(float(score_threshold) - expected_score) > tolerance:
                totals["buy_score_threshold_mismatch"] += 1
                bucket["score_threshold_mismatch"] += 1

        z_threshold = _as_float(row.get("buy_zscore_threshold"))
        if z_threshold is not None:
            totals["buy_zscore_threshold_populated"] += 1
            bucket["zscore_threshold_populated"] += 1
            if abs(float(z_threshold) - expected_z) > tolerance:
                totals["buy_zscore_threshold_mismatch"] += 1
                bucket["zscore_threshold_mismatch"] += 1

    total_rows = max(int(totals["total_buy_eval_rows"]), 1)
    totals["buy_score_actual_population_pct"] = round((totals["buy_score_actual_populated"] / total_rows) * 100.0, 2)
    totals["buy_score_threshold_population_pct"] = round(
        (totals["buy_score_threshold_populated"] / total_rows) * 100.0,
        2,
    )
    totals["buy_zscore_threshold_population_pct"] = round(
        (totals["buy_zscore_threshold_populated"] / total_rows) * 100.0,
        2,
    )
    totals["buy_score_threshold_mismatch_pct"] = round(
        (totals["buy_score_threshold_mismatch"] / total_rows) * 100.0,
        2,
    )
    totals["buy_zscore_threshold_mismatch_pct"] = round(
        (totals["buy_zscore_threshold_mismatch"] / total_rows) * 100.0,
        2,
    )

    return {
        "window_start_ts": float(start_ts),
        "window_end_ts": float(end_ts),
        "window_hours": round((end_ts - start_ts) / 3600.0, 4),
        "expected_thresholds": {
            "mean_reversion_score": _expected_score_threshold(cfg, "mean_reversion"),
            "trend_pullback_score": _expected_score_threshold(cfg, "trend_pullback"),
            "breakout_momentum_score": _expected_score_threshold(cfg, "breakout_momentum"),
            "volatility_scalper_score": _expected_score_threshold(cfg, "volatility_scalper"),
            "mean_reversion_zscore": _expected_zscore_threshold(cfg, "mean_reversion"),
            "volatility_scalper_zscore": _expected_zscore_threshold(cfg, "volatility_scalper"),
        },
        "totals": totals,
        "by_route": by_route,
    }


def _to_markdown(report: dict[str, Any]) -> str:
    totals = report.get("totals", {})
    by_route = report.get("by_route", {})
    lines = [
        "# Threshold Contract Audit",
        "",
        f"- Window (hours): `{report.get('window_hours')}`",
        f"- Buy eval rows: `{totals.get('total_buy_eval_rows')}`",
        f"- buy_score_actual populated: `{totals.get('buy_score_actual_population_pct')}%`",
        f"- buy_score_threshold populated: `{totals.get('buy_score_threshold_population_pct')}%`",
        f"- buy_zscore_threshold populated: `{totals.get('buy_zscore_threshold_population_pct')}%`",
        f"- score threshold mismatch: `{totals.get('buy_score_threshold_mismatch')}` ({totals.get('buy_score_threshold_mismatch_pct')}%)",
        f"- zscore threshold mismatch: `{totals.get('buy_zscore_threshold_mismatch')}` ({totals.get('buy_zscore_threshold_mismatch_pct')}%)",
        "",
        "## By Route",
        "",
        "| Route | Count | Score Pop % | Z Pop % | Score Mismatch % | Z Mismatch % |",
        "|---|---:|---:|---:|---:|---:|",
    ]
    for route in sorted(by_route.keys()):
        row = by_route[route]
        count = max(int(row.get("count", 0)), 1)
        score_pop = round((int(row.get("score_threshold_populated", 0)) / count) * 100.0, 2)
        z_pop = round((int(row.get("zscore_threshold_populated", 0)) / count) * 100.0, 2)
        score_mm = round((int(row.get("score_threshold_mismatch", 0)) / count) * 100.0, 2)
        z_mm = round((int(row.get("zscore_threshold_mismatch", 0)) / count) * 100.0, 2)
        lines.append(f"| `{route}` | {count} | {score_pop}% | {z_pop}% | {score_mm}% | {z_mm}% |")
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description="Audit score/z-score threshold contract against runtime decision audit rows.")
    parser.add_argument("--hours", type=float, default=12.0)
    parser.add_argument("--json-out", default="")
    parser.add_argument("--md-out", default="")
    args = parser.parse_args()

    now = time.time()
    start_ts = now - max(float(args.hours), 0.1) * 3600.0

    state_dir = _state_dir()
    cfg_path = state_dir / "config.json"
    decision_path = state_dir / "decision_audit.jsonl"
    cfg = _load_json(cfg_path, {})
    if not isinstance(cfg, dict):
        raise RuntimeError(f"Invalid config at {cfg_path}")
    rows = _load_jsonl(decision_path)

    report = build_threshold_contract_report(
        cfg=cfg,
        rows=rows,
        start_ts=start_ts,
        end_ts=now,
    )
    report["state_dir"] = str(state_dir)

    reports_dir = state_dir / "reports"
    reports_dir.mkdir(parents=True, exist_ok=True)
    stamp = time.strftime("%Y%m%d-%H%M%S", time.gmtime(now))

    json_out = Path(args.json_out) if str(args.json_out).strip() else reports_dir / f"threshold_contract_audit_{stamp}.json"
    md_out = Path(args.md_out) if str(args.md_out).strip() else reports_dir / f"threshold_contract_audit_{stamp}.md"

    json_out.write_text(json.dumps(report, indent=2), encoding="utf-8")
    md_out.write_text(_to_markdown(report), encoding="utf-8")

    print(
        json.dumps(
            {
                "json_report": str(json_out),
                "md_report": str(md_out),
                "totals": report.get("totals"),
                "expected_thresholds": report.get("expected_thresholds"),
            },
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
