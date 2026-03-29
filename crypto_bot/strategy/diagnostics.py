from strategy.regime import detect_regime
from strategy.legacy.scoring_adapter import score_indicators

try:
    from analysis.data_analysis import calculate_support_resistance
except ModuleNotFoundError:
    from crypto_bot.analysis.data_analysis import calculate_support_resistance

_structure_cache: dict[str, dict] = {}


def _structure_fingerprint(symbol: str, prices: list[float]) -> tuple:
    if not prices:
        return (symbol, 0)
    tail = prices[-64:]
    rounded = tuple(round(value, 8) for value in tail)
    return (
        symbol,
        len(prices),
        round(prices[0], 8),
        round(prices[-1], 8),
        round(min(prices), 8),
        round(max(prices), 8),
        hash(rounded),
    )


def compute_buy_diagnostics(
    *,
    snapshot,
    price,
    momentum,
    high_24h,
    low_24h,
    atr,
    z_score,
    regime_cfg,
    parse_numeric,
):
    regime = detect_regime(snapshot, regime_cfg)
    volatility = parse_numeric(atr, fallback=None)

    range_pos = None
    if high_24h > low_24h:
        range_pos = (price - low_24h) / (high_24h - low_24h)
        range_pos = max(0.0, min(1.0, range_pos))

    rsi = parse_numeric(snapshot.get("rsi"), fallback=None)
    if rsi is None:
        if range_pos is not None:
            rsi = range_pos * 100.0
        elif z_score is not None:
            rsi = max(0.0, min(100.0, 50.0 + (z_score * 10.0)))
        else:
            rsi = 50.0

    structure = 0.0
    recent_prices = snapshot.get("recent_prices")
    if isinstance(recent_prices, list):
        valid_prices = []
        for raw in recent_prices:
            value = parse_numeric(raw, fallback=None)
            if value is None or value <= 0:
                continue
            valid_prices.append(value)

        if len(valid_prices) >= 5:
            symbol = str(snapshot.get("symbol", "")).strip().upper()
            fingerprint = _structure_fingerprint(symbol, valid_prices)
            cached = _structure_cache.get(symbol)
            if (
                isinstance(cached, dict)
                and cached.get("fingerprint") == fingerprint
                and isinstance(cached.get("structure"), (int, float))
            ):
                structure = float(cached.get("structure"))
            else:
                try:
                    support, resistance = calculate_support_resistance(
                        valid_prices,
                        window=min(14, len(valid_prices)),
                    )
                    if price <= support * 1.01:
                        structure = 1.0
                    elif price >= resistance * 0.995:
                        structure = -1.0
                    else:
                        structure = 0.0
                except Exception:
                    structure = 0.0
                if symbol:
                    _structure_cache[symbol] = {
                        "fingerprint": fingerprint,
                        "structure": structure,
                    }

    indicators = {
        "rsi": rsi,
        "momentum": parse_numeric(momentum, fallback=0.0),
        "structure": structure,
    }

    score = score_indicators(
        regime=regime,
        indicators=indicators,
        range_pos=range_pos if range_pos is not None else 0.0,
    )
    return regime, float(score), range_pos, volatility


def compute_scalper_diagnostics(
    *,
    snapshot,
    price,
    momentum,
    high_24h,
    low_24h,
    atr,
    z_score,
    regime_cfg,
    scalper_cfg,
    parse_numeric,
):
    regime = detect_regime(snapshot, regime_cfg)
    volatility = parse_numeric(atr, fallback=None)

    range_pos = None
    if high_24h > low_24h:
        range_pos = (price - low_24h) / (high_24h - low_24h)
        range_pos = max(0.0, min(1.0, range_pos))

    score = 0.0
    min_atr = scalper_cfg.get("min_atr", 0.008)
    if volatility is not None:
        if volatility >= min_atr:
            score += 45
            score += min((volatility - min_atr) / max(min_atr, 1e-9), 1.0) * 20.0
        else:
            score += max(volatility / max(min_atr, 1e-9), 0.0) * 35.0

    momentum_value = parse_numeric(momentum, fallback=0.0) or 0.0
    if momentum_value > 0:
        score += min(momentum_value / 2.0, 1.0) * 20.0

    spread_bps = parse_numeric(snapshot.get("spread_bps"), fallback=None)
    max_spread_bps = max(scalper_cfg.get("max_spread_bps", 120.0), 1e-9)
    if spread_bps is not None:
        if spread_bps <= max_spread_bps:
            score += 15.0
        else:
            penalty = min(((spread_bps - max_spread_bps) / max_spread_bps) * 30.0, 40.0)
            score -= penalty

    entry_z_score_max = scalper_cfg.get("entry_z_score_max")
    if z_score is not None and entry_z_score_max is not None:
        if z_score <= entry_z_score_max:
            score += 15.0
        elif z_score >= 1.2:
            score -= 15.0

    if range_pos is not None:
        max_range_pos = scalper_cfg.get("max_range_pos")
        if max_range_pos is not None and range_pos <= max_range_pos:
            score += 10.0
        elif range_pos > 0.8:
            score -= 10.0

    if regime in {"trend_down", "breakout_down", "choppy", "unknown"}:
        score -= 10.0
    elif regime in {"trend_up", "momentum_up", "breakout_up"}:
        score += 5.0

    score = max(0.0, min(score, 100.0))
    return regime, float(score), range_pos, volatility


def record_symbol_metrics(
    *,
    symbol,
    regime,
    score,
    volatility,
    last_regime_state,
    last_score_state,
    last_volatility_state,
    parse_numeric,
    score_epsilon,
    volatility_epsilon,
):
    changed = False

    if last_regime_state.get(symbol) != regime:
        last_regime_state[symbol] = regime
        changed = True

    previous_score = parse_numeric(last_score_state.get(symbol), fallback=None)
    if previous_score is None or abs(previous_score - score) > score_epsilon:
        last_score_state[symbol] = float(score)
        changed = True

    if volatility is None:
        if symbol in last_volatility_state:
            last_volatility_state.pop(symbol, None)
            changed = True
    else:
        previous_volatility = parse_numeric(
            last_volatility_state.get(symbol),
            fallback=None,
        )
        if (
            previous_volatility is None
            or abs(previous_volatility - volatility) > volatility_epsilon
        ):
            last_volatility_state[symbol] = float(volatility)
            changed = True

    return changed
