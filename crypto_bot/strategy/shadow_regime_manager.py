from __future__ import annotations

from strategy import strategy_runtime_state as rt


def record_shadow_regime_metrics(
    *,
    symbol,
    snapshot,
    candidate_regime,
    cfg,
    update_regime_shadow_state,
    logger,
):
    shadow_row, changed = update_regime_shadow_state(
        symbol=symbol,
        snapshot=snapshot,
        candidate_regime=candidate_regime,
        shadow_state=rt._shadow_regime_state,
        cfg=cfg,
    )
    if not changed:
        return

    rt._metrics_dirty = True
    if shadow_row.get("switched"):
        logger.info(
            f"REGIME_SHADOW {symbol} | "
            f"candidate={shadow_row['candidate_regime']} "
            f"stable={shadow_row['stable_regime']} "
            f"conf={shadow_row['confidence']:.3f} "
            f"confirmations={shadow_row['confirmations']} "
            f"switched=1"
        )
    else:
        logger.debug(
            f"REGIME_SHADOW {symbol} | "
            f"candidate={shadow_row['candidate_regime']} "
            f"stable={shadow_row['stable_regime']} "
            f"conf={shadow_row['confidence']:.3f} "
            f"confirmations={shadow_row['confirmations']} "
            f"switched=0"
        )


def should_force_shadow_refresh(*, symbol, cfg, route_eval_ts, parse_numeric, router_flag, router_max_route_age_seconds):
    force_shadow_refresh = router_flag(cfg, "auto_use_current_cycle_shadow", False)
    if force_shadow_refresh:
        return True

    symbol_key = str(symbol or "").strip().upper()
    shadow_row = rt._shadow_regime_state.get(symbol_key, {})
    last_update_ts = parse_numeric(
        shadow_row.get("last_update_ts") if isinstance(shadow_row, dict) else None,
        fallback=0.0,
    ) or 0.0
    max_route_age_seconds = router_max_route_age_seconds(cfg)
    return last_update_ts <= 0 or (route_eval_ts - last_update_ts) > max_route_age_seconds
