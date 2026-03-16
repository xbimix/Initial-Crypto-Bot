from __future__ import annotations

import time


def _as_float(value, default=0.0):
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _as_int(value, default=0):
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _clamp(value: float, lower: float, upper: float) -> float:
    return max(lower, min(upper, value))


def _router_shadow_cfg(cfg: dict) -> tuple[int, int]:
    strategy_defaults = cfg.get("strategy_defaults", {})
    router = strategy_defaults.get("router", {}) if isinstance(strategy_defaults, dict) else {}
    if not isinstance(router, dict):
        router = {}

    confirmations_required = max(_as_int(router.get("confirmations_required"), 2), 1)
    cooldown_seconds = max(_as_int(router.get("regime_cooldown_seconds"), 0), 0)
    return confirmations_required, cooldown_seconds


def _confidence_from_snapshot(snapshot: dict, candidate_regime: str) -> float:
    quality_ok = snapshot.get("data_quality_ok", True) is True
    trade_count = max(_as_float(snapshot.get("trade_count"), 0.0), 0.0)
    atr = max(_as_float(snapshot.get("atr"), 0.0), 0.0)
    spread_bps = _as_float(snapshot.get("spread_bps"), 0.0)
    momentum = abs(_as_float(snapshot.get("momentum_norm"), 0.0))
    price = _as_float(snapshot.get("price"), 0.0)
    high = _as_float(snapshot.get("high_24h"), 0.0)
    low = _as_float(snapshot.get("low_24h"), 0.0)

    confidence = 0.32
    confidence += _clamp(trade_count / 60.0, 0.0, 0.24)
    confidence += 0.12 if atr > 0 else -0.10
    confidence += 0.10 if quality_ok else -0.18

    if spread_bps > 0:
        if spread_bps <= 40:
            confidence += 0.08
        elif spread_bps <= 120:
            confidence += 0.03
        else:
            confidence -= 0.08

    if candidate_regime in {"trend_up", "trend_down", "dump", "spike"}:
        confidence += _clamp(momentum / 8.0, 0.0, 0.10)

    if price > 0 and high > low > 0:
        range_pct = (high - low) / price
        confidence += _clamp(range_pct / 0.08, 0.0, 0.08)

    if candidate_regime == "unknown":
        confidence = min(confidence, 0.25)

    return round(_clamp(confidence, 0.0, 0.99), 4)


def _normalize_state_row(raw: dict) -> dict:
    if not isinstance(raw, dict):
        raw = {}

    candidate_regime = str(raw.get("candidate_regime", "unknown") or "unknown")
    stable_regime = str(raw.get("stable_regime", candidate_regime) or candidate_regime)
    confirmations = max(_as_int(raw.get("confirmations"), 0), 0)
    confidence = _clamp(_as_float(raw.get("confidence"), 0.0), 0.0, 0.99)
    last_update_ts = max(_as_float(raw.get("last_update_ts"), 0.0), 0.0)
    last_switch_ts = max(_as_float(raw.get("last_switch_ts"), 0.0), 0.0)
    switched = bool(raw.get("switched", False))

    return {
        "candidate_regime": candidate_regime,
        "stable_regime": stable_regime,
        "confirmations": confirmations,
        "confidence": round(confidence, 4),
        "last_update_ts": last_update_ts,
        "last_switch_ts": last_switch_ts,
        "switched": switched,
    }


def normalize_shadow_state(raw_state: dict | None) -> dict[str, dict]:
    if not isinstance(raw_state, dict):
        return {}

    normalized = {}
    for raw_symbol, raw_row in raw_state.items():
        symbol = str(raw_symbol or "").strip().upper()
        if not symbol:
            continue
        normalized[symbol] = _normalize_state_row(raw_row)
    return normalized


def update_regime_shadow_state(
    *,
    symbol: str,
    snapshot: dict,
    candidate_regime: str,
    shadow_state: dict,
    cfg: dict,
    now_ts: float | None = None,
) -> tuple[dict, bool]:
    symbol_key = str(symbol or "").strip().upper()
    if not symbol_key:
        return {}, False

    if now_ts is None:
        now_ts = time.time()

    row = _normalize_state_row(shadow_state.get(symbol_key))
    prev_row = dict(row)
    previous_candidate = row.get("candidate_regime", "unknown")
    previous_stable = row.get("stable_regime", "unknown")
    previous_confirmations = max(_as_int(row.get("confirmations"), 0), 0)
    previous_confidence = _clamp(_as_float(row.get("confidence"), 0.0), 0.0, 0.99)
    last_switch_ts = max(_as_float(row.get("last_switch_ts"), 0.0), 0.0)

    confirmations_required, cooldown_seconds = _router_shadow_cfg(cfg)
    if previous_candidate == candidate_regime:
        confirmations = previous_confirmations + 1
    else:
        confirmations = 1

    stable_regime = previous_stable
    switched = False
    cooldown_ready = (cooldown_seconds <= 0) or ((now_ts - last_switch_ts) >= cooldown_seconds)
    if stable_regime in {"", "unknown"} and candidate_regime:
        stable_regime = candidate_regime
        switched = stable_regime != previous_stable
        last_switch_ts = now_ts if switched else last_switch_ts
    elif (
        candidate_regime
        and candidate_regime != stable_regime
        and confirmations >= confirmations_required
        and cooldown_ready
    ):
        stable_regime = candidate_regime
        switched = True
        last_switch_ts = now_ts

    confidence_raw = _confidence_from_snapshot(snapshot, candidate_regime)
    confidence = (0.6 * previous_confidence) + (0.4 * confidence_raw)
    confidence = round(_clamp(confidence, 0.0, 0.99), 4)

    updated = {
        "candidate_regime": candidate_regime,
        "stable_regime": stable_regime,
        "confirmations": confirmations,
        "confidence": confidence,
        "last_update_ts": float(now_ts),
        "last_switch_ts": float(last_switch_ts),
        "switched": switched,
    }
    shadow_state[symbol_key] = updated
    changed = any(
        updated.get(key) != prev_row.get(key)
        for key in (
            "candidate_regime",
            "stable_regime",
            "confirmations",
            "confidence",
            "last_switch_ts",
            "switched",
        )
    )
    return updated, changed
