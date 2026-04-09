from __future__ import annotations

import time
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class RuntimeSafetyResult:
    """
    Structured runtime safety decision/result payload.
    """

    allowed: bool
    blocked_reason: str | None
    pause_until: float
    state_changed: bool
    counters: dict[str, float | int | str | None] = field(default_factory=dict)
    thresholds: dict[str, float | int | str | None] = field(default_factory=dict)


@dataclass(frozen=True)
class RuntimeSafetyState:
    daily_loss_close_all_day: str | None = None
    consecutive_execution_failures: int = 0
    execution_fail_pause_until: float = 0.0
    freshness_degraded_streak: int = 0
    freshness_guard_active: bool = False
    freshness_block_reason: str | None = None


class RuntimeSafetyService:
    def __init__(
        self,
        *,
        cfg: dict,
        risk_manager,
        logger,
        event_hook: Callable[[str, RuntimeSafetyResult], None] | None = None,
        initial_state: RuntimeSafetyState | None = None,
    ):
        self.cfg = cfg
        self.risk = risk_manager
        self.logger = logger
        self._event_hook = event_hook
        state = initial_state or RuntimeSafetyState()
        self._daily_loss_close_all_day = state.daily_loss_close_all_day
        self._consecutive_execution_failures = max(int(state.consecutive_execution_failures), 0)
        self._execution_fail_pause_until = max(float(state.execution_fail_pause_until), 0.0)
        self._freshness_degraded_streak = max(int(state.freshness_degraded_streak), 0)
        self._freshness_guard_active = bool(state.freshness_guard_active)
        self._freshness_block_reason = (
            str(state.freshness_block_reason).strip()
            if state.freshness_block_reason is not None
            else None
        )

    def export_state(self) -> RuntimeSafetyState:
        return RuntimeSafetyState(
            daily_loss_close_all_day=self._daily_loss_close_all_day,
            consecutive_execution_failures=self._consecutive_execution_failures,
            execution_fail_pause_until=self._execution_fail_pause_until,
            freshness_degraded_streak=self._freshness_degraded_streak,
            freshness_guard_active=self._freshness_guard_active,
            freshness_block_reason=self._freshness_block_reason,
        )

    def update_config(self, cfg: dict):
        self.cfg = cfg

    @staticmethod
    def _safe_float(value: Any, default: float | None = None) -> float | None:
        try:
            return float(value)
        except (TypeError, ValueError):
            return default

    def _failure_limits(self) -> tuple[int, int]:
        risk_cfg = self.cfg.get("risk", {})
        if not isinstance(risk_cfg, dict):
            return 5, 180
        max_failures = int(self._safe_float(risk_cfg.get("max_consecutive_execution_failures"), 5) or 5)
        pause_seconds = int(self._safe_float(risk_cfg.get("execution_failure_pause_seconds"), 180) or 180)
        return max(max_failures, 1), max(pause_seconds, 1)

    def failure_limits(self) -> tuple[int, int]:
        return self._failure_limits()

    def _freshness_guard_limits(self) -> tuple[bool, int]:
        market_data_cfg = self.cfg.get("market_data", {})
        if not isinstance(market_data_cfg, dict):
            return True, 3
        slo_cfg = market_data_cfg.get("freshness_slo", {})
        if not isinstance(slo_cfg, dict):
            slo_cfg = {}

        enabled_raw = slo_cfg.get("entry_block_on_degraded", True)
        if isinstance(enabled_raw, bool):
            enabled = enabled_raw
        else:
            enabled = str(enabled_raw).strip().lower() not in {"0", "false", "no", "off"}
        threshold_raw = self._safe_float(slo_cfg.get("entry_block_after_degraded_cycles"), 3)
        threshold = max(int(threshold_raw or 3), 1)
        return enabled, threshold

    def _emit(self, name: str, result: RuntimeSafetyResult):
        if not callable(self._event_hook):
            return
        try:
            self._event_hook(name, result)
        except Exception as exc:
            self.logger.warning(f"Runtime safety event hook failed ({name}): {exc}")

    def check_buy_allowed(self, symbol: str, *, now_epoch: float | None = None) -> RuntimeSafetyResult:
        now = float(now_epoch) if now_epoch is not None else time.time()
        daily_loss_state = self.risk.daily_loss_state()
        max_failures, pause_seconds = self._failure_limits()
        freshness_guard_enabled, freshness_block_after = self._freshness_guard_limits()

        counters: dict[str, float | int | str | None] = {
            "consecutive_execution_failures": self._consecutive_execution_failures,
            "daily_loss_realized_usd": self._safe_float(daily_loss_state.get("realized_usd"), 0.0) or 0.0,
            "daily_loss_day": daily_loss_state.get("day"),
            "freshness_degraded_streak": self._freshness_degraded_streak,
            "freshness_guard_active": bool(self._freshness_guard_active),
            "freshness_entry_block_reason": self._freshness_block_reason,
        }
        thresholds: dict[str, float | int | str | None] = {
            "max_consecutive_execution_failures": max_failures,
            "execution_failure_pause_seconds": pause_seconds,
            "daily_loss_limit_usd": self._safe_float(daily_loss_state.get("limit_usd"), 0.0) or 0.0,
            "freshness_entry_block_enabled": freshness_guard_enabled,
            "freshness_block_after_cycles": freshness_block_after,
        }

        remaining = int(self._execution_fail_pause_until - now)
        if remaining > 0:
            counters["pause_remaining_seconds"] = remaining
            result = RuntimeSafetyResult(
                allowed=False,
                blocked_reason="execution_failure_pause_active",
                pause_until=self._execution_fail_pause_until,
                state_changed=False,
                counters=counters,
                thresholds=thresholds,
            )
            self.logger.warning(
                f"BUY blocked for {symbol} (execution failures pause active for {remaining}s)"
            )
            self._emit("buy_blocked_execution_pause", result)
            return result

        if bool(self._freshness_guard_active):
            result = RuntimeSafetyResult(
                allowed=False,
                blocked_reason="freshness_slo_degraded",
                pause_until=self._execution_fail_pause_until,
                state_changed=False,
                counters=counters,
                thresholds=thresholds,
            )
            self.logger.warning(
                f"BUY blocked for {symbol} (freshness SLO degraded streak={self._freshness_degraded_streak} "
                f"reason={self._freshness_block_reason or 'unspecified'})"
            )
            self._emit("buy_blocked_freshness_slo", result)
            return result

        if bool(daily_loss_state.get("buy_paused", False)):
            result = RuntimeSafetyResult(
                allowed=False,
                blocked_reason="daily_loss_buy_paused",
                pause_until=self._execution_fail_pause_until,
                state_changed=False,
                counters=counters,
                thresholds=thresholds,
            )
            self.logger.info(
                f"BUY blocked for {symbol} (daily loss limit reached: "
                f"{counters['daily_loss_realized_usd']:.2f} <= -{thresholds['daily_loss_limit_usd']:.2f})"
            )
            self._emit("buy_blocked_daily_loss", result)
            return result

        return RuntimeSafetyResult(
            allowed=True,
            blocked_reason=None,
            pause_until=self._execution_fail_pause_until,
            state_changed=False,
            counters=counters,
            thresholds=thresholds,
        )

    def record_execution_success(self) -> RuntimeSafetyResult:
        state_changed = bool(
            self._consecutive_execution_failures > 0 or self._execution_fail_pause_until > 0.0
        )
        self._consecutive_execution_failures = 0
        self._execution_fail_pause_until = 0.0
        max_failures, pause_seconds = self._failure_limits()
        result = RuntimeSafetyResult(
            allowed=True,
            blocked_reason=None,
            pause_until=self._execution_fail_pause_until,
            state_changed=state_changed,
            counters={"consecutive_execution_failures": self._consecutive_execution_failures},
            thresholds={
                "max_consecutive_execution_failures": max_failures,
                "execution_failure_pause_seconds": pause_seconds,
            },
        )
        if state_changed:
            self._emit("execution_failure_state_reset", result)
        return result

    def record_freshness_slo(self, slo: dict | None) -> RuntimeSafetyResult:
        freshness_guard_enabled, freshness_block_after = self._freshness_guard_limits()
        if not isinstance(slo, dict):
            slo = {}
        status = str(slo.get("status") or "UNKNOWN").strip().upper() or "UNKNOWN"
        degraded = status == "DEGRADED"
        entry_block_reason = str(slo.get("entry_block_reason") or "").strip() or None

        previous_active = bool(self._freshness_guard_active)
        previous_streak = int(self._freshness_degraded_streak)
        if degraded:
            self._freshness_degraded_streak += 1
        else:
            self._freshness_degraded_streak = 0

        self._freshness_guard_active = bool(
            freshness_guard_enabled and self._freshness_degraded_streak >= freshness_block_after
        )
        self._freshness_block_reason = entry_block_reason if self._freshness_guard_active else None
        state_changed = (
            previous_active != self._freshness_guard_active
            or previous_streak != self._freshness_degraded_streak
        )
        blocked_reason = "freshness_slo_degraded" if self._freshness_guard_active else None
        result = RuntimeSafetyResult(
            allowed=not self._freshness_guard_active,
            blocked_reason=blocked_reason,
            pause_until=self._execution_fail_pause_until,
            state_changed=state_changed,
            counters={
                "freshness_status": status,
                "freshness_degraded_streak": self._freshness_degraded_streak,
                "freshness_guard_active": bool(self._freshness_guard_active),
                "freshness_entry_block_reason": self._freshness_block_reason,
            },
            thresholds={
                "freshness_entry_block_enabled": freshness_guard_enabled,
                "freshness_block_after_cycles": freshness_block_after,
            },
        )
        if previous_active != self._freshness_guard_active:
            event_name = (
                "freshness_entry_guard_activated"
                if self._freshness_guard_active
                else "freshness_entry_guard_cleared"
            )
            self._emit(event_name, result)
        return result

    def record_execution_failure(
        self,
        *,
        reason: str | None = None,
        now_epoch: float | None = None,
    ) -> RuntimeSafetyResult:
        now = float(now_epoch) if now_epoch is not None else time.time()
        self._consecutive_execution_failures += 1
        max_failures, pause_seconds = self._failure_limits()
        state_changed = False
        blocked_reason = None
        if self._consecutive_execution_failures >= max_failures:
            pause_until = now + pause_seconds
            state_changed = pause_until != self._execution_fail_pause_until
            self._execution_fail_pause_until = pause_until
            blocked_reason = "execution_failure_pause_activated"
            self.logger.warning(
                "Execution kill-switch pause activated: "
                f"failures={self._consecutive_execution_failures} "
                f"pause_seconds={pause_seconds} reason={reason or 'unknown'}"
            )
        result = RuntimeSafetyResult(
            allowed=True,
            blocked_reason=blocked_reason,
            pause_until=self._execution_fail_pause_until,
            state_changed=state_changed,
            counters={"consecutive_execution_failures": self._consecutive_execution_failures},
            thresholds={
                "max_consecutive_execution_failures": max_failures,
                "execution_failure_pause_seconds": pause_seconds,
            },
        )
        if blocked_reason:
            self._emit("execution_pause_activated", result)
        return result

    def enforce_daily_loss_controls(
        self,
        *,
        open_symbols: Iterable[str],
        get_position: Callable[[str], dict | None],
        execute_sell: Callable[[str, float, str], bool],
        snapshot_fetcher: Callable[[str, dict], dict | None] | None,
    ) -> RuntimeSafetyResult:
        daily_loss_state = self.risk.daily_loss_state()
        day_key = daily_loss_state.get("day")
        max_failures, pause_seconds = self._failure_limits()

        counters: dict[str, float | int | str | None] = {
            "consecutive_execution_failures": self._consecutive_execution_failures,
            "daily_loss_realized_usd": self._safe_float(daily_loss_state.get("realized_usd"), 0.0) or 0.0,
            "closed_positions": 0,
            "daily_loss_day": day_key,
        }
        thresholds: dict[str, float | int | str | None] = {
            "daily_loss_limit_usd": self._safe_float(daily_loss_state.get("limit_usd"), 0.0) or 0.0,
            "max_consecutive_execution_failures": max_failures,
            "execution_failure_pause_seconds": pause_seconds,
        }

        if not bool(daily_loss_state.get("close_all", False)):
            return RuntimeSafetyResult(
                allowed=True,
                blocked_reason=None,
                pause_until=self._execution_fail_pause_until,
                state_changed=False,
                counters=counters,
                thresholds=thresholds,
            )

        if day_key and self._daily_loss_close_all_day == day_key:
            return RuntimeSafetyResult(
                allowed=False,
                blocked_reason="daily_loss_close_all_already_executed",
                pause_until=self._execution_fail_pause_until,
                state_changed=False,
                counters=counters,
                thresholds=thresholds,
            )

        symbols = list(open_symbols)
        if not symbols:
            self._daily_loss_close_all_day = day_key
            result = RuntimeSafetyResult(
                allowed=False,
                blocked_reason="daily_loss_close_all_no_open_positions",
                pause_until=self._execution_fail_pause_until,
                state_changed=True,
                counters=counters,
                thresholds=thresholds,
            )
            self._emit("daily_loss_close_all_no_positions", result)
            return result

        closed = 0
        for symbol in symbols:
            sell_price = None
            if callable(snapshot_fetcher):
                try:
                    snapshot = snapshot_fetcher(symbol, self.cfg)
                except Exception:
                    snapshot = None
                if isinstance(snapshot, dict):
                    price_candidate = self._safe_float(snapshot.get("price"), None)
                    if price_candidate is not None and price_candidate > 0:
                        sell_price = price_candidate

            if sell_price is None:
                position = get_position(symbol) or {}
                fallback_price = self._safe_float(position.get("price"), None)
                if fallback_price is not None and fallback_price > 0:
                    sell_price = fallback_price

            if sell_price is None:
                continue

            if execute_sell(symbol, sell_price, "daily_loss_limit_close_all"):
                closed += 1

        counters["closed_positions"] = closed
        self._daily_loss_close_all_day = day_key
        result = RuntimeSafetyResult(
            allowed=closed > 0,
            blocked_reason=None if closed > 0 else "daily_loss_close_all_no_executable_positions",
            pause_until=self._execution_fail_pause_until,
            state_changed=True,
            counters=counters,
            thresholds=thresholds,
        )
        if closed > 0:
            self.logger.warning(
                f"Daily loss close-all executed: closed={closed} "
                f"realized_today={counters['daily_loss_realized_usd']:.2f} "
                f"limit={thresholds['daily_loss_limit_usd']:.2f}"
            )
            self._emit("daily_loss_close_all_executed", result)
        return result
