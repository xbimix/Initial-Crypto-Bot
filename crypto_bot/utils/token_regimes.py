from __future__ import annotations

from typing import Any

TOKEN_REGIME_AUTO = "AUTO"
TOKEN_REGIME_MEAN_REVERSION = "MEAN_REVERSION"
TOKEN_REGIME_TREND_PULLBACK = "TREND_PULLBACK"
TOKEN_REGIME_BREAKOUT_MOMENTUM = "BREAKOUT_MOMENTUM"
TOKEN_REGIME_OBSERVE_ONLY = "OBSERVE_ONLY"

TOKEN_REGIME_VALUES = (
    TOKEN_REGIME_AUTO,
    TOKEN_REGIME_MEAN_REVERSION,
    TOKEN_REGIME_TREND_PULLBACK,
    TOKEN_REGIME_BREAKOUT_MOMENTUM,
    TOKEN_REGIME_OBSERVE_ONLY,
)

_TOKEN_REGIME_SET = set(TOKEN_REGIME_VALUES)


def normalize_symbol(value: Any) -> str:
    if not isinstance(value, str):
        return ""
    return value.strip().upper()


def normalize_token_regime(value: Any, *, default: str = TOKEN_REGIME_AUTO) -> str:
    raw = str(value or "").strip().upper()
    return raw if raw in _TOKEN_REGIME_SET else default


def is_valid_token_regime(value: Any) -> bool:
    if not isinstance(value, str):
        return False
    return value.strip().upper() in _TOKEN_REGIME_SET
