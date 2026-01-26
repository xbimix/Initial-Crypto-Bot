class RiskManager:
    def __init__(self, risk_pct=0.0075, max_trades=1):
        self.risk_pct = risk_pct
        self.max_trades = max_trades

    def position_size(self, balance, entry, stop):
        risk_amount = balance * self.risk_pct
        stop_distance = abs(entry - stop)
        if stop_distance == 0:
            return 0
        return round(risk_amount / stop_distance, 6)
