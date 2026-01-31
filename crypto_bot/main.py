import time

from utils.logger import setup_logger
from utils.config_loader import load_config

from data.market_data import fetch_ohlcv
from strategy.strategy_engine import evaluate_symbol
from trading.executor import Executor

logger = setup_logger()


def main():
    logger.info("🚀 RevBot starting (paper mode default)")

    cfg = load_config()
    executor = Executor(cfg)

    while True:
        try:
            cfg = load_config()  # hot reload config

            if not cfg.get("enabled", False):
                logger.info("⏸ Bot disabled — waiting...")
                time.sleep(5)
                continue

            logger.info("❤️ Heartbeat — bot running")

            for symbol in cfg["symbols"]:
                logger.info(f"🔍 Processing {symbol}")

                ohlcv = fetch_ohlcv(
                    symbol=symbol,
                    interval=cfg["interval"],
                    limit=cfg["lookback"]
                )

                if not ohlcv:
                    logger.warning(f"⚠️ No market data for {symbol}")
                    continue

                decision = evaluate_symbol(symbol, ohlcv, cfg)

                executor.handle_decision(decision)

            time.sleep(10)

        except Exception as e:
            logger.exception(f"🔥 Main loop error: {e}")
            time.sleep(5)


if __name__ == "__main__":
    main()


    # while True:
    #     try:
    #         cfg = load_config()

    #         if not cfg.get("enabled"):
    #             logger.info("⏸ Bot disabled — waiting...")
    #             time.sleep(5)
    #             continue

    #         logger.info("❤️ Heartbeat — bot running")

    #         for symbol in cfg["symbols"]:
    #             logger.info(f"🔍 Evaluating {symbol}")

    #             # Strategy + execution will be plugged in Phase 4+
    #             # For now, we log so silence is impossible

    #         time.sleep(10)

    #     except Exception as e:
    #         logger.exception(f"🔥 Fatal loop error: {e}")
    #         time.sleep(5)

if __name__ == "__main__":
    main()
