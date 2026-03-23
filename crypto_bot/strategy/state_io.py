import time


def _sanitize_symbol_map(raw_map, *, key_name, logger):
    if not isinstance(raw_map, dict):
        if raw_map is not None:
            logger.warning(f"Strategy state key '{key_name}' malformed; expected object, got {type(raw_map).__name__}")
        return {}

    sanitized = {}
    dropped = 0
    for raw_key, value in raw_map.items():
        if not isinstance(raw_key, str):
            dropped += 1
            continue
        symbol = raw_key.strip().upper()
        if (not symbol) or ("-" not in symbol):
            dropped += 1
            continue
        sanitized[symbol] = value
    if dropped > 0:
        logger.warning(f"Strategy state key '{key_name}' dropped {dropped} malformed symbol entries")
    return sanitized


def paper_state_mtime(paper_state_file):
    try:
        return paper_state_file.stat().st_mtime
    except OSError:
        return None


def save_strategy_state(
    *,
    state_dir,
    strategy_state_file,
    write_json_file,
    state_maps,
    shadow_regime_state,
):
    state_dir.mkdir(parents=True, exist_ok=True)
    state = dict(state_maps)
    state["shadow_regime_state"] = shadow_regime_state
    write_json_file(strategy_state_file, state)
    return time.time()


def load_strategy_state(
    *,
    strategy_state_file,
    read_json_file,
    normalize_shadow_state,
    state_maps,
    shadow_regime_state,
    logger,
):
    if not strategy_state_file.exists():
        return

    try:
        state = read_json_file(strategy_state_file, default={})
        if not isinstance(state, dict):
            state = {}

        for key, mapping in state_maps.items():
            mapping.update(_sanitize_symbol_map(state.get(key, {}), key_name=key, logger=logger))

        shadow_regime_state.update(
            normalize_shadow_state(state.get("shadow_regime_state", {}))
        )
        logger.info("Strategy state restored")
    except Exception as e:
        logger.error(f"Failed to load strategy state: {e}")


def sync_with_broker_state(
    *,
    paper_state_file,
    read_json_file,
    parse_numeric,
    entry_price,
    entry_time,
    profit_lock,
    peak_pnl,
    last_momentum,
    last_signal,
    metadata_maps,
    entry_route_state=None,
    entry_regime_state=None,
    exit_policy_state=None,
    entry_confidence_state=None,
    entry_timestamp_state=None,
    entry_route_eval_ts_state=None,
    entry_regime_eval_ts_state=None,
    save_strategy_state,
    logger,
):
    if not paper_state_file.exists():
        return

    try:
        data = read_json_file(paper_state_file, default={})
        if not isinstance(data, dict):
            data = {}

        positions = data.get("positions", {})
        if not isinstance(positions, dict):
            logger.warning("Strategy sync: paper positions malformed; expected object")
            positions = {}
        broker_symbols = set(positions)
        state_changed = False

        for symbol in list(entry_price.keys()):
            if symbol not in broker_symbols:
                entry_price.pop(symbol, None)
                entry_time.pop(symbol, None)
                profit_lock.pop(symbol, None)
                peak_pnl.pop(symbol, None)
                last_momentum.pop(symbol, None)
                last_signal.pop(symbol, None)
                state_changed = True
                logger.info(f"Strategy sync: removed stale state for {symbol}")

        for symbol in list(entry_time.keys()):
            if symbol not in broker_symbols:
                entry_time.pop(symbol, None)
                state_changed = True

        for symbol in list(profit_lock.keys()):
            if symbol not in broker_symbols:
                profit_lock.pop(symbol, None)
                state_changed = True

        for symbol in list(peak_pnl.keys()):
            if symbol not in broker_symbols:
                peak_pnl.pop(symbol, None)
                state_changed = True

        for symbol in list(last_momentum.keys()):
            if symbol not in broker_symbols:
                last_momentum.pop(symbol, None)
                state_changed = True

        for symbol in list(last_signal.keys()):
            if symbol not in broker_symbols:
                last_signal.pop(symbol, None)
                state_changed = True

        for mapping in metadata_maps:
            for symbol in list(mapping.keys()):
                if symbol in broker_symbols:
                    continue
                mapping.pop(symbol, None)
                state_changed = True

        position_policy_maps = (
            entry_route_state,
            entry_regime_state,
            exit_policy_state,
            entry_confidence_state,
            entry_timestamp_state,
            entry_route_eval_ts_state,
            entry_regime_eval_ts_state,
        )
        for mapping in position_policy_maps:
            if not isinstance(mapping, dict):
                continue
            for symbol in list(mapping.keys()):
                if symbol in broker_symbols:
                    continue
                mapping.pop(symbol, None)
                state_changed = True

        for symbol, pos in positions.items():
            if not isinstance(pos, dict):
                logger.warning(f"Strategy sync: skipping malformed position row for {symbol}")
                continue
            restored_entry_price = pos.get("price")
            restored_entry_time = parse_numeric(pos.get("entry_time"), fallback=None)
            if restored_entry_time is None:
                restored_entry_time = time.time()
            if symbol not in entry_price:
                entry_price[symbol] = restored_entry_price
                entry_time[symbol] = restored_entry_time
                profit_lock[symbol] = None
                last_signal[symbol] = "BUY"
                state_changed = True
                logger.info(f"Strategy sync: restored {symbol} @ {restored_entry_price}")
            elif entry_price.get(symbol) != restored_entry_price:
                entry_price[symbol] = restored_entry_price
                state_changed = True
                logger.info(
                    f"Strategy sync: reconciled {symbol} entry to {restored_entry_price}"
                )
            if entry_time.get(symbol) != restored_entry_time:
                entry_time[symbol] = restored_entry_time
                state_changed = True

            if symbol not in profit_lock:
                profit_lock[symbol] = None
                state_changed = True
            if symbol not in peak_pnl:
                peak_pnl[symbol] = 0.0
                state_changed = True
            if last_signal.get(symbol) != "BUY":
                last_signal[symbol] = "BUY"
                state_changed = True

            # Route/exit contract restore (for open positions).
            stored_route = str(pos.get("entry_route") or "").strip().lower()
            if stored_route not in {"mean_reversion", "trend_pullback", "breakout_momentum", "observe_only", "volatility_scalper"}:
                stored_route = "mean_reversion"
            stored_exit_policy = str(pos.get("exit_policy") or "").strip().lower()
            if stored_exit_policy not in {"mr_exit", "trend_exit", "breakout_exit", "scalper_exit"}:
                if stored_route == "trend_pullback":
                    stored_exit_policy = "trend_exit"
                elif stored_route == "breakout_momentum":
                    stored_exit_policy = "breakout_exit"
                elif stored_route == "volatility_scalper":
                    stored_exit_policy = "scalper_exit"
                else:
                    stored_exit_policy = "mr_exit"
            stored_regime = str(pos.get("entry_regime") or "MIXED_OR_UNCLEAR")
            stored_confidence = parse_numeric(pos.get("entry_confidence"), fallback=None)
            stored_entry_timestamp = parse_numeric(pos.get("entry_timestamp"), fallback=restored_entry_time) or restored_entry_time
            stored_route_eval_ts = parse_numeric(pos.get("route_eval_ts"), fallback=stored_entry_timestamp) or stored_entry_timestamp
            stored_regime_eval_ts = parse_numeric(pos.get("regime_eval_ts"), fallback=stored_entry_timestamp) or stored_entry_timestamp

            if isinstance(entry_route_state, dict) and entry_route_state.get(symbol) != stored_route:
                entry_route_state[symbol] = stored_route
                state_changed = True
            if isinstance(entry_regime_state, dict) and entry_regime_state.get(symbol) != stored_regime:
                entry_regime_state[symbol] = stored_regime
                state_changed = True
            if isinstance(exit_policy_state, dict) and exit_policy_state.get(symbol) != stored_exit_policy:
                exit_policy_state[symbol] = stored_exit_policy
                state_changed = True
            if isinstance(entry_confidence_state, dict):
                if entry_confidence_state.get(symbol) != stored_confidence:
                    entry_confidence_state[symbol] = stored_confidence
                    state_changed = True
            if isinstance(entry_timestamp_state, dict) and entry_timestamp_state.get(symbol) != stored_entry_timestamp:
                entry_timestamp_state[symbol] = stored_entry_timestamp
                state_changed = True
            if isinstance(entry_route_eval_ts_state, dict) and entry_route_eval_ts_state.get(symbol) != stored_route_eval_ts:
                entry_route_eval_ts_state[symbol] = stored_route_eval_ts
                state_changed = True
            if isinstance(entry_regime_eval_ts_state, dict) and entry_regime_eval_ts_state.get(symbol) != stored_regime_eval_ts:
                entry_regime_eval_ts_state[symbol] = stored_regime_eval_ts
                state_changed = True

        if state_changed:
            save_strategy_state()
    except Exception as e:
        logger.exception(f"Strategy state sync failed: {e}")
