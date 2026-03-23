from __future__ import annotations

from typing import Any, Callable

from strategy.diagnostics import compute_buy_diagnostics


def compute_mr_score_bundle(
    *,
    snapshot: dict[str, Any],
    price: float,
    momentum: float,
    high_24h: float,
    low_24h: float,
    atr: float | None,
    z_score: float | None,
    regime_cfg: dict[str, Any],
    parse_numeric: Callable[[Any, Any], float | None],
) -> tuple[str, float, float | None, float | None]:
    return compute_buy_diagnostics(
        snapshot=snapshot,
        price=price,
        momentum=momentum,
        high_24h=high_24h,
        low_24h=low_24h,
        atr=atr,
        z_score=z_score,
        regime_cfg=regime_cfg,
        parse_numeric=parse_numeric,
    )
