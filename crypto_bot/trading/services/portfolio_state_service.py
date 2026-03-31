from __future__ import annotations


class PortfolioStateService:
    def __init__(self, paper_broker, risk_manager, logger):
        self.paper = paper_broker
        self.risk = risk_manager
        self.logger = logger

    @staticmethod
    def _safe_float(value, default=None):
        try:
            return float(value)
        except (TypeError, ValueError):
            return default

    def has_open_position(self, symbol: str) -> bool:
        return self.paper.has_position(symbol)

    def open_symbols(self) -> list[str]:
        return list(self.paper.positions.keys())

    def open_positions_count(self) -> int:
        return len(self.paper.positions)

    def get_position(self, symbol: str) -> dict | None:
        position = self.paper.get_position(symbol)
        return position if isinstance(position, dict) else None

    def current_allocated_usd(self) -> tuple[float, dict[str, float]]:
        allocated = 0.0
        by_symbol: dict[str, float] = {}
        for symbol, pos in self.paper.positions.items():
            entry_price = self._safe_float(pos.get("price"), 0.0) or 0.0
            entry_size = self._safe_float(pos.get("size"), 0.0) or 0.0
            position_value = max(entry_price, 0.0) * max(entry_size, 0.0)
            allocated += position_value
            by_symbol[symbol] = position_value
        return allocated, by_symbol

    def sync_risk_with_broker(self):
        for symbol, pos in self.paper.positions.items():
            self.risk.register_position(
                symbol,
                {
                    "entry": pos.get("price"),
                    "size": pos.get("size"),
                },
            )
        if self.paper.positions:
            self.logger.info("Executor sync: RiskManager aligned with broker state")

    def register_buy_fill(self, *, symbol: str, fallback_price: float, fallback_size: float):
        self.risk.mark_trade(symbol)
        position = self.get_position(symbol) or {}
        fill_price = self._safe_float(position.get("price"), fallback_price) or fallback_price
        fill_size = self._safe_float(position.get("size"), fallback_size) or fallback_size
        self.risk.register_position(
            symbol,
            {
                "entry": fill_price,
                "size": fill_size,
                "entry_time": position.get("entry_time"),
            },
        )
        return fill_price, fill_size

    def register_sell_fill(self, *, symbol: str, execution_report: dict):
        self.risk.mark_trade(symbol)
        position_closed = bool(execution_report.get("position_closed", True))
        if position_closed:
            self.risk.close_position(symbol)
            return True
        position = self.get_position(symbol) or {}
        self.risk.register_position(
            symbol,
            {
                "entry": position.get("price"),
                "size": position.get("size"),
                "entry_time": position.get("entry_time"),
            },
        )
        return False
