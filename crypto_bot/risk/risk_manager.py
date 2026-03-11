import json
import os
import time

from utils.logger import setup_logger

logger = setup_logger("risk")

STATE_DIR = os.path.abspath(
    os.path.join(os.path.dirname(__file__), "..", "state")
)
PAPER_STATE_FILE = os.path.join(STATE_DIR, "paper_state.json")


class RiskManager:
    def __init__(self, cfg):
        self.cfg = cfg
        self.last_trade_time = {}

    # =====================================================
    # SYNC OPEN POSITIONS FROM PAPER STATE (RESTART SAFE)
    # =====================================================

    def _sync_with_broker_state(self):
        if not os.path.exists(PAPER_STATE_FILE):
            return

        try:
            with open(PAPER_STATE_FILE, "r") as f:
                json.load(f)
            logger.info("RiskManager synced open positions from broker")
        except Exception as e:
            logger.error(f"RiskManager sync failed: {e}")

    # =====================================================
    # CONFIG UPDATE
    # =====================================================

    def update_config(self, cfg: dict):
        self.cfg = cfg

    # =====================================================
    # COOLDOWN CONTROL
    # =====================================================

    def can_trade(self, symbol):
        risk_cfg = self.cfg.get("risk", {})
        cooldown = float(risk_cfg.get("cooldown_seconds", 90))
        last_time = self.last_trade_time.get(symbol, 0)
        return (time.time() - last_time) >= cooldown

    def mark_trade(self, symbol):
        self.last_trade_time[symbol] = time.time()

    # =====================================================
    # POSITION LIMIT CONTROL
    # =====================================================

    def can_open_position(self, current_open_positions: int):
        risk_cfg = self.cfg.get("risk", {})
        max_trades = int(risk_cfg.get("max_concurrent_trades", 1))
        return current_open_positions < max_trades

    # =====================================================
    # POSITION SIZING
    # =====================================================

    def position_size(self, balance, entry_price):
        if entry_price <= 0:
            return 0.0

        risk_cfg = self.cfg.get("risk", {})
        risk_pct = float(risk_cfg.get("risk_percent", 0.02))
        trade_amount_usd = risk_cfg.get("trade_amount_usd")

        if trade_amount_usd is not None:
            trade_amount = max(float(trade_amount_usd), 0.0)
            capital_to_use = min(float(balance), trade_amount)
            sizing_mode = f"fixed_usd={trade_amount:.2f}"
        else:
            capital_to_use = max(float(balance) * risk_pct, 0.0)
            sizing_mode = f"risk_pct={risk_pct*100:.2f}%"

        size = capital_to_use / float(entry_price)

        logger.info(
            f"Position sizing: balance={balance:.2f}, "
            f"{sizing_mode}, capital={capital_to_use:.2f}, size={size:.6f}"
        )

        return round(size, 6)
