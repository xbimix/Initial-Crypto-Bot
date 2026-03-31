from __future__ import annotations


class ExecutionService:
    def __init__(self, paper_broker):
        self.paper = paper_broker

    def execute_buy(
        self,
        *,
        symbol: str,
        price: float,
        size: float,
        reason: str,
        trade_meta: dict | None = None,
    ) -> tuple[bool, dict]:
        ok = bool(self.paper.buy(symbol, price, size, reason, trade_meta=trade_meta))
        report = self.paper.last_execution_report if isinstance(self.paper.last_execution_report, dict) else {}
        return ok, dict(report)

    def execute_sell(
        self,
        *,
        symbol: str,
        price: float,
        reason: str,
        trade_meta: dict | None = None,
    ) -> tuple[bool, dict]:
        ok = bool(self.paper.sell(symbol, price, reason, trade_meta=trade_meta))
        report = self.paper.last_execution_report if isinstance(self.paper.last_execution_report, dict) else {}
        return ok, dict(report)
