from __future__ import annotations

from typing import Any, Callable

from strategy.exits.mr_exit import evaluate_mr_exit


def evaluate_shared_non_mr_exit(
    *,
    symbol: str,
    price: float,
    momentum: float,
    entry: float | None,
    entry_ts: float | None,
    z_score: float | None,
    first_activation: float,
    initial_lock: float,
    profit_levels: list[list[float]],
    trailing_activation: float,
    trailing_gap: float,
    reset_below_activation: bool,
    max_negative_z_score: float,
    profit_lock_state: dict[str, float | None],
    peak_pnl_state: dict[str, float],
    entry_price_state: dict[str, float],
    save_strategy_state: Callable[[], None],
    decision: Callable[[str, str, float, float, str], dict[str, Any]],
    logger: Any,
    stale_exit_max_hold_seconds: float = 0.0,
    stale_exit_min_pnl_pct: float = 0.0025,
) -> dict[str, Any] | None:
    # Shared non-MR exit base. Uses the same conservative lock model by default.
    return evaluate_mr_exit(
        symbol=symbol,
        price=price,
        momentum=momentum,
        entry=entry,
        entry_ts=entry_ts,
        z_score=z_score,
        first_activation=first_activation,
        initial_lock=initial_lock,
        profit_levels=profit_levels,
        trailing_activation=trailing_activation,
        trailing_gap=trailing_gap,
        reset_below_activation=reset_below_activation,
        max_negative_z_score=max_negative_z_score,
        profit_lock_state=profit_lock_state,
        peak_pnl_state=peak_pnl_state,
        entry_price_state=entry_price_state,
        save_strategy_state=save_strategy_state,
        decision=decision,
        logger=logger,
        stale_exit_max_hold_seconds=stale_exit_max_hold_seconds,
        stale_exit_min_pnl_pct=stale_exit_min_pnl_pct,
    )
