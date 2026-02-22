import time
import os
import json
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
      #  self.open_positions = {}
       # self._sync_with_broker_state()

    # =====================================================
    # SYNC OPEN POSITIONS FROM PAPER STATE (RESTART SAFE)
    # =====================================================

    def _sync_with_broker_state(self):
        if not os.path.exists(PAPER_STATE_FILE):
            return

        try:
            with open(PAPER_STATE_FILE, "r") as f:
                data = json.load(f)

            positions = data.get("positions", {})

            # for symbol, pos in positions.items():
            #     self.open_positions[symbol] = {
            #         "entry": pos.get("price"),
            #         "size": pos.get("size"),
            #     }

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
        cooldown = self.cfg["risk"]["cooldown_seconds"]
        last_time = self.last_trade_time.get(symbol, 0)
        return (time.time() - last_time) >= cooldown

    def mark_trade(self, symbol):
        self.last_trade_time[symbol] = time.time()

    # =====================================================
    # POSITION LIMIT CONTROL
    # =====================================================

    def can_open_position(self, current_open_positions: int):
        max_trades = self.cfg["risk"]["max_concurrent_trades"]
        return current_open_positions < max_trades


    # def register_position(self, symbol, position):
    #     self.open_positions[symbol] = position

    # def close_position(self, symbol):
    #     self.open_positions.pop(symbol, None)

    # =====================================================
    # POSITION SIZING
    # =====================================================

    def position_size(self, balance, entry_price):
        risk_pct = self.cfg["risk"]["risk_percent"]
        risk_amount = balance * risk_pct
        size = risk_amount / entry_price

        logger.info(
            f"📐 Position sizing: balance={balance:.2f}, "
            f"risk={risk_pct*100:.1f}%, size={size:.6f}"
        )

        return round(size, 6)

# import time
# from utils.logger import setup_logger

# logger = setup_logger("risk")
# logger.info("RiskManager loaded")

# class RiskManager:
#     def __init__(self, cfg: dict):
#         self.cfg = cfg
#         self.last_trade_time = {}
#         self.open_positions = {}
#     # --------------------------------------------------
#     # HOT RELOAD
#     # --------------------------------------------------

#     def update_config(self, cfg: dict):
#         self.cfg = cfg

#     # --------------------------------------------------
#     # COOLDOWN
#     # --------------------------------------------------

#     def can_trade(self, symbol: str) -> bool:
#         cooldown = self.cfg["risk"]["cooldown_seconds"]
#         last_time = self.last_trade_time.get(symbol, 0)
#         return (time.time() - last_time) >= cooldown

#     def mark_trade(self, symbol: str):
#         self.last_trade_time[symbol] = time.time()

#     # --------------------------------------------------
#     # POSITION LIMITS
#     # --------------------------------------------------

#     def can_open_position(self, current_open_positions: int) -> bool:
#         max_trades = self.cfg["risk"]["max_concurrent_trades"]
#         return current_open_positions < max_trades
    
#     def register_position(self, symbol, position):
#         self.open_positions[symbol] = position

#     def close_position(self, symbol):
#         self.open_positions.pop(symbol, None)

#     # --------------------------------------------------
#     # POSITION SIZING
#     # --------------------------------------------------

#     def position_size(self, balance: float, entry_price: float) -> float:
#         risk_pct = self.cfg["risk"]["risk_percent"]

#         risk_amount = balance * risk_pct
#         size = risk_amount / entry_price

#         logger.info(
#             f"📐 Position sizing: balance={balance:.2f}, "
#             f"risk={risk_pct*100:.1f}%, size={size:.6f}"
#         )

#         return round(size, 6)
