from __future__ import annotations

import argparse
import json
import re
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

SCRIPT_DIR = Path(__file__).resolve().parent
REPO_ROOT = SCRIPT_DIR.parent
CRYPTO_BOT_DIR = REPO_ROOT / "crypto_bot"
if str(CRYPTO_BOT_DIR) not in sys.path:
    sys.path.insert(0, str(CRYPTO_BOT_DIR))

from strategy.regime import detect_regime
from strategy.regime_router import resolve_entry_route
from utils.token_regimes import (
    TOKEN_REGIME_AUTO,
    TOKEN_REGIME_MEAN_REVERSION,
    normalize_token_regime,
)

try:
    from strategy.regime_router import AUTO_DEFAULT_MIN_CONFIDENCE_SCORE
except ImportError:
    AUTO_DEFAULT_MIN_CONFIDENCE_SCORE = 68.0

SNAPSHOT_LINE_RE = re.compile(
    r"^\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2},\d+\s+\|\s+INFO\s+\|\s+SNAPSHOT\s+([A-Z0-9-]+)\s+\|\s+(.+)$"
)


def _read_json(path: Path, default: dict[str, Any]) -> dict[str, Any]:
    if not path.exists():
        return dict(default)
    try:
        raw = path.read_text(encoding="utf-8")
        parsed = json.loads(raw)
        if isinstance(parsed, dict):
            return parsed
    except Exception:
        pass
    return dict(default)


def _num(value: Any, default: float | None = None) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _normalize_symbol(value: Any) -> str:
    if not isinstance(value, str):
        return ""
    return value.strip().upper()


def _normalize_symbols(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    seen: set[str] = set()
    out: list[str] = []
    for row in value:
        symbol = _normalize_symbol(row)
        if not symbol or symbol in seen:
            continue
        seen.add(symbol)
        out.append(symbol)
    return out


def _normalize_strategy_name(value: Any) -> str:
    raw = str(value or "").strip().lower()
    if raw in {"volatility_scalper", "vol_scalper", "scalper"}:
        return "volatility_scalper"
    return "mean_reversion"


def _default_strategy_for_symbol(cfg: dict[str, Any], symbol: str) -> str:
    symbol_key = _normalize_symbol(symbol)
    if not symbol_key:
        return "mean_reversion"

    symbol_strategies = cfg.get("symbol_strategies", {})
    if isinstance(symbol_strategies, dict):
        for raw_symbol, raw_strategy in symbol_strategies.items():
            if _normalize_symbol(raw_symbol) != symbol_key:
                continue
            return _normalize_strategy_name(raw_strategy)

    strategy_overrides = cfg.get("strategy_overrides", {})
    if isinstance(strategy_overrides, dict):
        for raw_symbol, override in strategy_overrides.items():
            if _normalize_symbol(raw_symbol) != symbol_key:
                continue
            mode = override
            if isinstance(override, dict):
                mode = override.get("strategy", override.get("mode"))
            return _normalize_strategy_name(mode)

    scalper_cfg = cfg.get("volatility_scalper", {})
    if isinstance(scalper_cfg, dict):
        scalper_enabled = scalper_cfg.get("enabled", True) is not False
        scalper_symbols = set()
        raw_symbols = scalper_cfg.get("symbols", [])
        if isinstance(raw_symbols, list):
            for item in raw_symbols:
                normalized = _normalize_symbol(item)
                if normalized:
                    scalper_symbols.add(normalized)
        if scalper_enabled and symbol_key in scalper_symbols:
            return "volatility_scalper"

    return "mean_reversion"


def _configured_regime(cfg: dict[str, Any], symbol: str) -> str:
    token_regimes = cfg.get("token_regimes", {})
    if not isinstance(token_regimes, dict):
        return TOKEN_REGIME_MEAN_REVERSION
    raw = token_regimes.get(_normalize_symbol(symbol))
    return normalize_token_regime(raw, default=TOKEN_REGIME_MEAN_REVERSION)


def _parse_snapshot_fields(raw_fields: str) -> dict[str, str]:
    values: dict[str, str] = {}
    for token in raw_fields.split():
        if "=" not in token:
            continue
        key, value = token.split("=", 1)
        values[key.strip()] = value.strip().strip(",")
    return values


def _read_latest_snapshots(log_path: Path, symbols: list[str]) -> dict[str, dict[str, Any]]:
    snapshots: dict[str, dict[str, Any]] = {}
    if not log_path.exists() or not symbols:
        return snapshots

    wanted = set(symbols)
    try:
        lines = log_path.read_text(encoding="utf-8", errors="ignore").splitlines()
    except Exception:
        return snapshots

    for line in reversed(lines):
        match = SNAPSHOT_LINE_RE.match(line)
        if not match:
            continue

        symbol = match.group(1)
        if symbol not in wanted or symbol in snapshots:
            continue

        fields = _parse_snapshot_fields(match.group(2))
        quality = fields.get("quality")
        snapshots[symbol] = {
            "symbol": symbol,
            "price": _num(fields.get("price"), 0.0) or 0.0,
            "momentum_norm": _num(fields.get("mom_norm"), 0.0) or 0.0,
            "trade_count": _num(fields.get("trades"), _num(fields.get("points"), 0.0)) or 0.0,
            "high_24h": _num(fields.get("24h_high"), 0.0) or 0.0,
            "low_24h": _num(fields.get("24h_low"), 0.0) or 0.0,
            "atr": _num(fields.get("atr_raw"), 0.0) or 0.0,
            "vwap": _num(fields.get("vwap"), None),
            "ema_50": _num(fields.get("ema_50"), None),
            "ema_200": _num(fields.get("ema_200"), None),
            "ema_50_slope": _num(fields.get("ema_50_slope"), None),
            "spread_bps": _num(fields.get("spread_bps"), 0.0) or 0.0,
            "data_quality_ok": quality in (None, "ok"),
            "data_quality_reason": quality or "ok",
        }
        if len(snapshots) >= len(wanted):
            break

    return snapshots


def _fallback_snapshot(symbol: str) -> dict[str, Any]:
    return {
        "symbol": symbol,
        "price": 0.0,
        "momentum_norm": 0.0,
        "trade_count": 0.0,
        "high_24h": 0.0,
        "low_24h": 0.0,
        "atr": 0.0,
        "vwap": None,
        "ema_50": None,
        "ema_200": None,
        "ema_50_slope": None,
        "spread_bps": 0.0,
        "data_quality_ok": False,
        "data_quality_reason": "missing_snapshot",
    }


def _trend_hint_without_ema(snapshot: dict[str, Any]) -> bool:
    price = _num(snapshot.get("price"), 0.0) or 0.0
    vwap = _num(snapshot.get("vwap"), None)
    momentum = _num(snapshot.get("momentum_norm"), 0.0) or 0.0
    if vwap is None:
        return False
    return (price > vwap and momentum > 0.25) or (price < vwap and momentum < -0.25)


def _safe_get_map(payload: dict[str, Any], key: str) -> dict[str, Any]:
    value = payload.get(key, {})
    if isinstance(value, dict):
        return value
    return {}


def _build_report(state_dir: Path) -> dict[str, Any]:
    config_path = state_dir / "config.json"
    strategy_path = state_dir / "strategy_state.json"
    log_path = state_dir / "bot.log"

    cfg = _read_json(config_path, {})
    strategy = _read_json(strategy_path, {})
    symbols = _normalize_symbols(cfg.get("symbols", []))

    router_cfg = {}
    if isinstance(cfg.get("strategy_defaults"), dict):
        router_cfg = cfg["strategy_defaults"].get("router", {})
    if not isinstance(router_cfg, dict):
        router_cfg = {}
    min_conf = float(
        router_cfg.get("auto_min_confidence", AUTO_DEFAULT_MIN_CONFIDENCE_SCORE)
        or AUTO_DEFAULT_MIN_CONFIDENCE_SCORE
    )
    min_conf = min_conf * 100.0 if 0 <= min_conf <= 1.0 else min_conf
    min_confirms = int(
        router_cfg.get("auto_min_confirmations", router_cfg.get("confirmations_required", 2))
        or 2
    )

    snapshots = _read_latest_snapshots(log_path, symbols)
    for symbol in symbols:
        snapshots.setdefault(symbol, _fallback_snapshot(symbol))

    explicit_regimes: set[str] = set()
    token_regimes = cfg.get("token_regimes", {})
    if isinstance(token_regimes, dict):
        for key in token_regimes.keys():
            symbol = _normalize_symbol(key)
            if symbol:
                explicit_regimes.add(symbol)

    last_detected_regime = _safe_get_map(strategy, "last_detected_regime")
    last_detected_conf = _safe_get_map(strategy, "last_detected_regime_confidence")
    last_effective_strategy = _safe_get_map(strategy, "last_effective_strategy")
    last_auto_fallback = _safe_get_map(strategy, "last_auto_fallback_reason")
    shadow_state = _safe_get_map(strategy, "shadow_regime_state")

    summary: dict[str, Any] = {
        "symbols_total": len(symbols),
        "auto_symbols": 0,
        "ema_missing_symbols": 0,
        "ema_missing_with_trend_hint": 0,
        "auto_routes": Counter(),
        "auto_fallback_reasons": Counter(),
        "detected_regimes": Counter(),
        "candidate_regimes": Counter(),
        "stable_regimes": Counter(),
    }

    rows: list[dict[str, Any]] = []
    for symbol in symbols:
        configured = _configured_regime(cfg, symbol)
        snapshot = snapshots[symbol]
        default_strategy = _default_strategy_for_symbol(cfg, symbol)
        route = resolve_entry_route(
            cfg=cfg,
            symbol=symbol,
            snapshot=snapshot,
            default_strategy=default_strategy,
            shadow_state=shadow_state,
        )
        snapshot_regime = detect_regime(snapshot, cfg.get("market_regime", {}))

        ema_missing = any(
            snapshot.get(key) is None
            for key in ("ema_50", "ema_200", "ema_50_slope")
        )
        trend_hint = _trend_hint_without_ema(snapshot)
        if ema_missing:
            summary["ema_missing_symbols"] += 1
            if trend_hint:
                summary["ema_missing_with_trend_hint"] += 1

        detected = route.get("detected_regime")
        detected_from_state = last_detected_regime.get(symbol)
        shadow_row = shadow_state.get(symbol, {}) if isinstance(shadow_state, dict) else {}
        if not isinstance(shadow_row, dict):
            shadow_row = {}
        shadow_candidate = str(shadow_row.get("candidate_regime") or "") or None
        shadow_stable = str(shadow_row.get("stable_regime") or "") or None
        shadow_confidence = shadow_row.get("confidence")
        shadow_confirmations = shadow_row.get("confirmations")

        candidate = shadow_candidate or detected_from_state or detected or "unknown"
        fallback_reason = route.get("auto_fallback_reason") or last_auto_fallback.get(symbol)
        effective_strategy = route.get("effective_strategy") or default_strategy

        if configured == TOKEN_REGIME_AUTO:
            summary["auto_symbols"] += 1
            summary["auto_routes"][str(effective_strategy or "unknown")] += 1
            summary["auto_fallback_reasons"][str(fallback_reason or "none")] += 1
            summary["detected_regimes"][str(detected or detected_from_state or "unknown")] += 1
            summary["candidate_regimes"][str(candidate)] += 1
            summary["stable_regimes"][str(shadow_stable or "unknown")] += 1

        rows.append(
            {
                "symbol": symbol,
                "configured": configured,
                "explicit": symbol in explicit_regimes,
                "default_strategy": default_strategy,
                "effective_strategy": effective_strategy,
                "fallback": fallback_reason,
                "detected": detected,
                "detected_from_state": detected_from_state,
                "detected_confidence": route.get("detected_regime_confidence"),
                "detected_confidence_from_state": last_detected_conf.get(symbol),
                "last_effective_strategy_state": last_effective_strategy.get(symbol),
                "min_confidence": min_conf,
                "min_confirmations": min_confirms,
                "shadow_candidate": shadow_candidate,
                "shadow_stable": shadow_stable,
                "shadow_confidence": shadow_confidence,
                "shadow_confirmations": shadow_confirmations,
                "snapshot_regime": snapshot_regime,
                "ema_missing": ema_missing,
                "trend_hint_no_ema": bool(ema_missing and trend_hint),
                "quality": snapshot.get("data_quality_reason"),
            }
        )

    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "state_dir": str(state_dir),
        "thresholds": {
            "auto_min_confidence": min_conf,
            "auto_min_confirmations": min_confirms,
        },
        "summary": {
            **{k: v for k, v in summary.items() if not isinstance(v, Counter)},
            "auto_routes": dict(summary["auto_routes"]),
            "auto_fallback_reasons": dict(summary["auto_fallback_reasons"]),
            "detected_regimes": dict(summary["detected_regimes"]),
            "candidate_regimes": dict(summary["candidate_regimes"]),
            "stable_regimes": dict(summary["stable_regimes"]),
        },
        "rows": rows,
    }


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Advisory-only regime precision report. Reads config/state/log data and "
            "explains AUTO regime routing outcomes without changing behavior."
        )
    )
    parser.add_argument(
        "--state-dir",
        default=str(CRYPTO_BOT_DIR / "state"),
        help="State directory containing config.json, strategy_state.json, and bot.log.",
    )
    parser.add_argument(
        "--out",
        default="",
        help="Optional output JSON file path. If omitted, prints report only.",
    )
    parser.add_argument(
        "--summary-only",
        action="store_true",
        help="Print only generated_at, thresholds, and summary.",
    )
    args = parser.parse_args()

    state_dir = Path(args.state_dir).resolve()
    report = _build_report(state_dir)
    payload = report
    if args.summary_only:
        payload = {
            "generated_at": report["generated_at"],
            "state_dir": report["state_dir"],
            "thresholds": report["thresholds"],
            "summary": report["summary"],
        }

    print(json.dumps(payload, indent=2))

    out_path_raw = str(args.out or "").strip()
    if out_path_raw:
        out_path = Path(out_path_raw).resolve()
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
        print(f"\nSaved full report to: {out_path}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
