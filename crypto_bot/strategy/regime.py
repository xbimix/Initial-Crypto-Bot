def _to_float(value, default=None):
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def detect_regime(snapshot: dict, regime_cfg: dict = None) -> str:
    """
    Adaptive regime detection with safer input handling and configurable thresholds.
    """
    regime_cfg = regime_cfg or {}

    momentum = _to_float(snapshot.get("momentum_norm"), 0.0)
    atr = _to_float(snapshot.get("atr"), 0.0)
    price = _to_float(snapshot.get("price"), 0.0)
    high = _to_float(snapshot.get("high_24h"), 0.0)
    low = _to_float(snapshot.get("low_24h"), 0.0)

    ema_50 = _to_float(snapshot.get("ema_50"))
    ema_200 = _to_float(snapshot.get("ema_200"))
    ema_50_slope = _to_float(snapshot.get("ema_50_slope"))

    dump_momentum = regime_cfg.get("dump_momentum", -1.2)
    spike_atr_pct = regime_cfg.get("spike_atr_pct", 0.015)
    spike_min_range_pos = regime_cfg.get("spike_min_range_pos", 0.40)
    accumulation_max_range_pos = regime_cfg.get("accumulation_max_range_pos", 0.30)
    accumulation_min_momentum = regime_cfg.get("accumulation_min_momentum", -0.2)
    range_max_width_pct = regime_cfg.get("range_max_width_pct", 0.04)

    if price is None or price <= 0 or high is None or low is None:
        return "unknown"

    range_width = high - low
    if range_width <= 0:
        return "unknown"

    raw_range_pos = (price - low) / range_width
    range_pos = max(0.0, min(1.0, raw_range_pos))
    range_pct = range_width / price
    atr_pct = atr / price if atr and atr > 0 else 0.0

    if momentum < dump_momentum:
        return "dump"

    if (
        ema_50 is not None
        and ema_200 is not None
        and ema_50_slope is not None
        and price < ema_50
        and ema_50 < ema_200
        and ema_50_slope < 0
    ):
        return "trend_down"

    if (
        ema_50 is not None
        and ema_200 is not None
        and ema_50_slope is not None
        and price > ema_50
        and ema_50 > ema_200
        and ema_50_slope > 0
    ):
        return "trend_up"

    if atr_pct > spike_atr_pct and range_pos > spike_min_range_pos:
        return "spike"

    if range_pos <= accumulation_max_range_pos and momentum > accumulation_min_momentum:
        return "accumulation"

    if range_pct < range_max_width_pct:
        return "range"

    return "chop"
