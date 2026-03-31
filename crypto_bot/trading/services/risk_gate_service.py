from __future__ import annotations

from typing import Any


class RiskGateService:
    def __init__(self, risk_manager, logger):
        self.risk = risk_manager
        self.logger = logger

    @staticmethod
    def _safe_float(value: Any, default: float | None = None) -> float | None:
        try:
            return float(value)
        except (TypeError, ValueError):
            return default

    def check_buy_preconditions(
        self,
        *,
        cfg: dict,
        symbol: str,
        volatility,
        trade_meta: dict | None,
        open_positions_count: int,
        symbol_open_positions: int,
        has_open_position: bool,
    ) -> str | None:
        if not self.risk.is_within_trade_window():
            self.logger.info(f"BUY blocked for {symbol} (outside UTC trade window)")
            return "outside_trade_window"

        risk_cfg = cfg.get("risk", {})
        if not isinstance(risk_cfg, dict):
            risk_cfg = {}
        if bool(risk_cfg.get("block_bad_market_quality", True)):
            quality = str((trade_meta or {}).get("data_quality_status") or "").strip().upper()
            if quality in {"STALE", "INSUFFICIENT", "UNSUPPORTED_WINDOW"}:
                self.logger.info(f"BUY blocked for {symbol} (market quality={quality})")
                return f"bad_market_quality:{quality.lower()}"

        if not self.risk.can_trade(symbol, volatility=volatility):
            self.logger.info(f"Cooldown active for {symbol}")
            return "cooldown_active"

        if not self.risk.can_open_position(open_positions_count):
            self.logger.info("Max concurrent trades reached")
            return "max_concurrent_trades"

        if not self.risk.can_open_position_for_symbol(symbol_open_positions):
            self.logger.info(f"Max concurrent trades reached for {symbol}")
            return "max_concurrent_trades_per_symbol"

        if has_open_position:
            self.logger.info(f"Position already open for {symbol}")
            return "position_already_open"
        return None

    def check_allocation_limits(
        self,
        *,
        symbol: str,
        trade_cost: float,
        current_allocated: float,
        current_symbol_allocated: float,
        equity: float,
    ) -> str | None:
        if not self.risk.can_open_under_max_trade_amount(current_allocated, trade_cost):
            self.logger.info("Max trade amount reached")
            return "max_trade_amount"

        exposure_block_reason = self.risk.exposure_block_reason(
            current_open_value_usd=current_allocated,
            current_symbol_value_usd=current_symbol_allocated,
            next_trade_cost_usd=trade_cost,
            equity_usd=equity,
        )
        if exposure_block_reason:
            self.logger.info(f"BUY blocked for {symbol} ({exposure_block_reason})")
            return str(exposure_block_reason)
        return None
