import time


def evaluate_sell(
    *,
    symbol,
    price,
    momentum,
    entry,
    z_score,
    first_activation,
    initial_lock,
    profit_levels,
    trailing_activation,
    trailing_gap,
    reset_below_activation,
    max_negative_z_score,
    profit_lock_state,
    peak_pnl_state,
    entry_price_state,
    save_strategy_state,
    decision,
    logger,
):
    if entry is None:
        return None
    if entry <= 0:
        logger.warning(f"{symbol} exit skipped due to invalid entry price: {entry}")
        return decision(symbol, "HOLD", price, momentum, "invalid_entry_price")

    pnl_pct = (price - entry) / entry
    current_lock = profit_lock_state.get(symbol)
    saved_peak = peak_pnl_state.get(symbol)
    peak_pnl = pnl_pct if saved_peak is None else max(saved_peak, pnl_pct)
    state_changed = False

    if pnl_pct < first_activation:
        reset_peak = max(pnl_pct, 0.0) if reset_below_activation else peak_pnl
        if peak_pnl_state.get(symbol) != reset_peak:
            peak_pnl_state[symbol] = reset_peak
            state_changed = True
        if reset_below_activation and current_lock is not None:
            profit_lock_state[symbol] = None
            state_changed = True
        if state_changed:
            save_strategy_state()
        return decision(symbol, "HOLD", price, momentum, "waiting_for_first_lock")

    if peak_pnl_state.get(symbol) != peak_pnl:
        peak_pnl_state[symbol] = peak_pnl
        state_changed = True

    if current_lock is None:
        current_lock = initial_lock

    for trigger, lock in profit_levels:
        if pnl_pct >= trigger:
            current_lock = max(current_lock, lock)

    if peak_pnl >= trailing_activation:
        current_lock = max(current_lock, peak_pnl - trailing_gap)

    previous_lock = profit_lock_state.get(symbol)
    if previous_lock != current_lock:
        profit_lock_state[symbol] = current_lock
        state_changed = True

    if state_changed:
        save_strategy_state()

    logger.info(
        f"{symbol} PNL={pnl_pct:.4f} | lock={current_lock:.4f} | "
        f"lock_price={(entry * (1 + current_lock)):.2f}"
    )

    if pnl_pct <= current_lock:
        if symbol not in entry_price_state:
            return decision(symbol, "HOLD", price, momentum, "desync_protection")

        return decision(
            symbol,
            "SELL",
            price,
            momentum,
            f"profit_lock_exit_{int(current_lock*100)}pct",
        )

    if z_score is not None and current_lock == 0.01 and z_score < max_negative_z_score:
        return decision(symbol, "SELL", price, momentum, "structural_break_exit")

    return decision(symbol, "HOLD", price, momentum, "in_position")


def evaluate_scalper_sell(
    *,
    symbol,
    price,
    momentum,
    entry,
    entry_ts,
    atr,
    z_score,
    scalper_cfg,
    entry_time_state,
    peak_pnl_state,
    parse_numeric,
    decision,
):
    if entry is None:
        return None

    now = time.time()
    if entry_ts is None:
        entry_ts = entry_time_state.get(symbol)
    entry_ts = parse_numeric(entry_ts, fallback=None)
    if entry_ts is None:
        entry_ts = now
        entry_time_state[symbol] = entry_ts

    atr_value = parse_numeric(atr, fallback=0.0) or 0.0
    min_move_pct = max(
        parse_numeric(scalper_cfg.get("min_move_pct"), fallback=0.0015) or 0.0015,
        0.0,
    )
    take_profit_pct = max(
        atr_value * max(scalper_cfg.get("take_profit_atr_mult", 0.6), 0.0),
        min_move_pct,
    )
    stop_loss_pct = max(
        atr_value * max(scalper_cfg.get("stop_loss_atr_mult", 0.35), 0.0),
        min_move_pct * 0.75,
    )
    max_hold_seconds = max(int(scalper_cfg.get("max_hold_seconds", 180)), 1)
    exit_z_score = parse_numeric(
        scalper_cfg.get("exit_z_score"),
        fallback=0.8,
    )

    pnl_pct = (price - entry) / entry
    peak_pnl_state[symbol] = max(peak_pnl_state.get(symbol, pnl_pct), pnl_pct)

    if pnl_pct >= take_profit_pct:
        return decision(symbol, "SELL", price, momentum, "scalper_take_profit")

    if pnl_pct <= -stop_loss_pct:
        return decision(symbol, "SELL", price, momentum, "scalper_stop_loss")

    if (
        z_score is not None
        and exit_z_score is not None
        and z_score >= exit_z_score
        and pnl_pct > 0
    ):
        return decision(symbol, "SELL", price, momentum, "scalper_vwap_exit")

    if (now - entry_ts) >= max_hold_seconds:
        return decision(symbol, "SELL", price, momentum, "scalper_time_stop")

    return decision(symbol, "HOLD", price, momentum, "scalper_in_position")
