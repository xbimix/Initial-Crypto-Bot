class RiskManager:
    def __init__(self, risk_percent=0.02):
        self.risk_percent = risk_percent

    def position_size(self, balance, entry_price, stop_price):
        """
        Calculate position size based on fixed risk percentage.
        """

        risk_amount = balance * self.risk_percent
        stop_distance = abs(entry_price - stop_price)

        if stop_distance <= 0:
            return 0

        size = risk_amount / stop_distance
        return round(size, 6)
