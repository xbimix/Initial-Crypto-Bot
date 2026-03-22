import time


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
            mapping.update(state.get(key, {}))

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

        for symbol, pos in positions.items():
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

        if state_changed:
            save_strategy_state()
    except Exception as e:
        logger.exception(f"Strategy state sync failed: {e}")
