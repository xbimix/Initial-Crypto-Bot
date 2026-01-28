import time

from utils.config_loader import load_config
from data.market_data import fetch_ohlcv
from strategy.strategy_engine import generate_signal
from trading.executor import execute_trade


POLL_INTERVAL = 5  # seconds (safe)


def main():
    print("🚀 Bot started")

    while True:
        try:
            cfg = load_config()

            # ---------------------------
            # Global enable / disable
            # ---------------------------
            if not cfg.get("enabled", False):
                time.sleep(POLL_INTERVAL)
                continue

            symbols = cfg.get("symbols", [])

            for symbol in symbols:
                ohlcv = fetch_ohlcv(symbol)
                signal = generate_signal(ohlcv, cfg)
                execute_trade(signal, symbol, cfg)

            time.sleep(POLL_INTERVAL)

        except Exception as e:
            print(f"[ERROR] {e}")
            time.sleep(10)


if __name__ == "__main__":
    main()
