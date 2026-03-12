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

    @staticmethod
    def _as_float(value, default):
        try:
            return float(value)
        except (TypeError, ValueError):
            return default

    def _volatility_scaling(self, volatility):
        risk_cfg = self.cfg.get("risk", {})
        if not isinstance(risk_cfg, dict):
            risk_cfg = {}

        scaling_cfg = risk_cfg.get("volatility_scaling", {})
        if not isinstance(scaling_cfg, dict):
            scaling_cfg = {}

        enabled = scaling_cfg.get("enabled", True) is not False
        vol = self._as_float(volatility, None)
        if not enabled or vol is None or vol <= 0:
            return {
                "bucket": "base",
                "cooldown_mult": 1.0,
                "size_mult": 1.0,
            }

        low_atr = max(self._as_float(scaling_cfg.get("low_atr"), 0.003), 0.0)
        high_atr = max(
            self._as_float(scaling_cfg.get("high_atr"), 0.009),
            low_atr + 1e-9,
        )

        if vol <= low_atr:
            bucket = "low"
            cooldown_mult = self._as_float(scaling_cfg.get("low_cooldown_mult"), 1.0)
            size_mult = self._as_float(scaling_cfg.get("low_size_mult"), 1.0)
        elif vol <= high_atr:
            bucket = "medium"
            cooldown_mult = self._as_float(scaling_cfg.get("medium_cooldown_mult"), 1.25)
            size_mult = self._as_float(scaling_cfg.get("medium_size_mult"), 0.85)
        else:
            bucket = "high"
            cooldown_mult = self._as_float(scaling_cfg.get("high_cooldown_mult"), 1.6)
            size_mult = self._as_float(scaling_cfg.get("high_size_mult"), 0.65)

        max_cooldown_mult = max(
            self._as_float(scaling_cfg.get("max_cooldown_mult"), 2.5),
            1.0,
        )
        min_size_mult = min(
            max(self._as_float(scaling_cfg.get("min_size_mult"), 0.30), 0.05),
            1.0,
        )

        cooldown_mult = min(max(cooldown_mult, 1.0), max_cooldown_mult)
        size_mult = min(max(size_mult, min_size_mult), 1.0)

        return {
            "bucket": bucket,
            "cooldown_mult": cooldown_mult,
            "size_mult": size_mult,
        }

    # =====================================================
    # COOLDOWN CONTROL
    # =====================================================

    def can_trade(self, symbol, volatility=None):
        risk_cfg = self.cfg.get("risk", {})
        cooldown = float(risk_cfg.get("cooldown_seconds", 90))
        scaling = self._volatility_scaling(volatility)
        cooldown *= scaling["cooldown_mult"]
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

    def position_size(self, balance, entry_price, volatility=None):
        if entry_price <= 0:
            return 0.0

        risk_cfg = self.cfg.get("risk", {})
        risk_pct = float(risk_cfg.get("risk_percent", 0.02))
        trade_amount_usd = risk_cfg.get("trade_amount_usd")
        scaling = self._volatility_scaling(volatility)

        if trade_amount_usd is not None:
            trade_amount = max(float(trade_amount_usd), 0.0)
            capital_to_use = min(float(balance), trade_amount)
            sizing_mode = f"fixed_usd={trade_amount:.2f}"
        else:
            capital_to_use = max(float(balance) * risk_pct, 0.0)
            sizing_mode = f"risk_pct={risk_pct*100:.2f}%"

        capital_to_use = min(
            max(capital_to_use * scaling["size_mult"], 0.0),
            float(balance),
        )
        size = capital_to_use / float(entry_price)

        logger.info(
            f"Position sizing: balance={balance:.2f}, "
            f"{sizing_mode}, vol_bucket={scaling['bucket']}, "
            f"capital={capital_to_use:.2f}, size={size:.6f}"
        )

        return round(size, 6)
