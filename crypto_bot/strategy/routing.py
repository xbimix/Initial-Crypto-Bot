from utils.token_regimes import (
    TOKEN_REGIME_MEAN_REVERSION,
    normalize_symbol as normalize_token_symbol,
    normalize_token_regime,
)


def router_cfg(cfg: dict) -> dict:
    strategy_defaults = cfg.get("strategy_defaults", {})
    if not isinstance(strategy_defaults, dict):
        return {}
    router = strategy_defaults.get("router", {})
    if not isinstance(router, dict):
        return {}
    return router


def router_flag(cfg: dict, key: str, default: bool = False) -> bool:
    raw = router_cfg(cfg).get(key)
    if isinstance(raw, bool):
        return raw
    if isinstance(raw, (int, float)):
        return bool(raw)
    if isinstance(raw, str):
        normalized = raw.strip().lower()
        if normalized in {"1", "true", "yes", "on"}:
            return True
        if normalized in {"0", "false", "no", "off"}:
            return False
    return default


def configured_regime_for_symbol(cfg: dict, symbol: str) -> str:
    token_regimes = cfg.get("token_regimes", {})
    if not isinstance(token_regimes, dict):
        return TOKEN_REGIME_MEAN_REVERSION
    symbol_key = normalize_token_symbol(symbol)
    if not symbol_key:
        return TOKEN_REGIME_MEAN_REVERSION
    raw = token_regimes.get(symbol_key)
    return normalize_token_regime(raw, default=TOKEN_REGIME_MEAN_REVERSION)


def advisory_has_required_fields(advisory: dict) -> bool:
    if not isinstance(advisory, dict):
        return False
    has_regime = any(
        isinstance(advisory.get(key), str) and advisory.get(key)
        for key in ("suggestedRegime", "suggested_regime", "detectedRegime", "detected_regime")
    )
    if not has_regime:
        return False
    def _is_numeric(value):
        try:
            float(value)
            return True
        except (TypeError, ValueError):
            return False

    has_confidence = any(
        _is_numeric(advisory.get(key))
        for key in ("confidenceScore", "confidence_score")
    )
    return has_confidence


def normalize_symbol(value):
    if not isinstance(value, str):
        return ""
    return value.strip().upper()


def normalize_strategy_name(value):
    raw = str(value or "").strip().lower()
    if raw in {"volatility_scalper", "vol_scalper", "scalper"}:
        return "volatility_scalper"
    return "mean_reversion"


def resolve_scalper_config(cfg, parse_numeric):
    raw = cfg.get("volatility_scalper", {})
    if not isinstance(raw, dict):
        raw = {}

    symbols = set()
    raw_symbols = raw.get("symbols", [])
    if isinstance(raw_symbols, list):
        for item in raw_symbols:
            symbol = normalize_symbol(item)
            if symbol:
                symbols.add(symbol)

    max_range_pos = parse_numeric(raw.get("max_range_pos"), fallback=0.65)
    if max_range_pos is not None:
        max_range_pos = max(0.0, min(1.0, max_range_pos))

    return {
        "enabled": raw.get("enabled", True) is not False,
        "symbols": symbols,
        "min_atr": max(parse_numeric(raw.get("min_atr"), fallback=0.008) or 0.008, 0.0),
        "min_trades": max(int(parse_numeric(raw.get("min_trades"), fallback=6) or 6), 1),
        "max_spread_bps": max(
            parse_numeric(raw.get("max_spread_bps"), fallback=120.0) or 120.0,
            0.0,
        ),
        "min_momentum": parse_numeric(raw.get("min_momentum"), fallback=0.2),
        "entry_z_score_max": parse_numeric(raw.get("entry_z_score_max"), fallback=-0.1),
        "exit_z_score": parse_numeric(raw.get("exit_z_score"), fallback=0.8),
        "take_profit_atr_mult": max(
            parse_numeric(raw.get("take_profit_atr_mult"), fallback=0.6) or 0.6,
            0.0,
        ),
        "stop_loss_atr_mult": max(
            parse_numeric(raw.get("stop_loss_atr_mult"), fallback=0.35) or 0.35,
            0.0,
        ),
        "max_hold_seconds": max(
            int(parse_numeric(raw.get("max_hold_seconds"), fallback=180) or 180),
            1,
        ),
        "min_move_pct": max(
            parse_numeric(raw.get("min_move_pct"), fallback=0.0015) or 0.0015,
            0.0,
        ),
        "min_score_to_buy": max(
            parse_numeric(raw.get("min_score_to_buy"), fallback=55.0) or 55.0,
            0.0,
        ),
        "max_range_pos": max_range_pos,
    }


def strategy_for_symbol(cfg, symbol, scalper_cfg):
    symbol_key = normalize_symbol(symbol)
    if not symbol_key:
        return "mean_reversion"

    symbol_strategies = cfg.get("symbol_strategies", {})
    if isinstance(symbol_strategies, dict):
        for raw_symbol, raw_strategy in symbol_strategies.items():
            if normalize_symbol(raw_symbol) != symbol_key:
                continue
            return normalize_strategy_name(raw_strategy)

    strategy_overrides = cfg.get("strategy_overrides", {})
    if isinstance(strategy_overrides, dict):
        for raw_symbol, override in strategy_overrides.items():
            if normalize_symbol(raw_symbol) != symbol_key:
                continue

            mode = override
            if isinstance(override, dict):
                mode = override.get("strategy", override.get("mode"))
            return normalize_strategy_name(mode)

    # Scalper routing is manual-only and must be keyed to explicit per-symbol
    # strategy toggle state (`symbol_strategies` / `strategy_overrides`).
    # Do not implicitly force scalper via volatility_scalper.symbols membership.
    return "mean_reversion"
