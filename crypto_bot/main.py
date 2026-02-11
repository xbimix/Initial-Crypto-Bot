import time
from utils.logger import setup_logger
from utils.config_loader import load_config

from data.market_data import fetch_market_snapshot
from strategy.strategy_engine import evaluate_symbol
from trading.executor import Executor

logger = setup_logger("main")

HEARTBEAT_INTERVAL = 60  # seconds


def main():
    logger.info("RevBot starting (paper mode default)")

    executor = None
    last_heartbeat = 0

    while True:
     try:
        cfg = load_config()

        if not cfg.get("enabled", False):
            logger.info("Bot disabled — waiting")
            time.sleep(5)
            continue

        if executor is None:
            executor = Executor(cfg)
        else:
            executor.update_config(cfg)

        now = time.time()
        if now - last_heartbeat > HEARTBEAT_INTERVAL:
            logger.info("Heartbeat — bot running")
            last_heartbeat = now

        symbols = list(dict.fromkeys(cfg["symbols"]))

        for symbol in symbols:

            # POSITION-AWARE FILTER
            if executor.has_open_position(symbol) and \
               executor.open_positions_count() >= cfg["risk"]["max_concurrent_trades"]:
                continue

            market = fetch_market_snapshot(symbol, cfg)
            if market is None:
                continue

            decision = evaluate_symbol(market, cfg)

            if decision["action"] != "HOLD":
                executor.handle_decision(decision)

            time.sleep(0.2)

        time.sleep(cfg.get("loop_sleep", 10))

     except Exception as e:
        logger.exception(f"Main loop error: {e}")
        time.sleep(5)
if __name__ == "__main__":
         main()

#     while True:
#         try:
#             cfg = load_config()  # hot reload

#             if not cfg.get("enabled", False):
#                 logger.info("Bot disabled — waiting")
#                 time.sleep(5)
#                 continue

#             if executor is None:
#                 executor = Executor(cfg)

#             now = time.time()
#             if now - last_heartbeat > HEARTBEAT_INTERVAL:
#                 logger.info("Heartbeat — bot running")
#                 last_heartbeat = now

#             symbols = list(dict.fromkeys(cfg["symbols"]))  # de-duplicate

#             for symbol in symbols:
#                 logger.info(f"Processing {symbol}")

#                 market = fetch_market_snapshot(symbol, cfg)
#                 if market is None:
#                     logger.warning(f"No market data for {symbol}")
#                     continue

#                 decision = evaluate_symbol(market, cfg)

#                 if decision["action"] != "HOLD":
#                     executor.handle_decision(decision)

#                 time.sleep(0.2)  # API pacing

#             time.sleep(cfg.get("loop_sleep", 10))

#         except Exception as e:
#             logger.exception(f"Main loop error: {e}")
#             time.sleep(5)


# if __name__ == "__main__":
#     main()
#---------------------------LAST WORKING STATE---------------------------

# main.py
# import time
# from utils.logger import setup_logger
# from utils.config_loader import load_config

# from data.market_data import fetch_market_snapshot
# from strategy.strategy_engine import evaluate_symbol
# from trading.executor import Executor

# logger = setup_logger("main")


# def main():
#     logger.info("RevBot starting (paper mode default)")

#     cfg = load_config()
#     executor = Executor(cfg)

#     while True:
#         try:
#             cfg = load_config()  # hot reload

#             if not cfg.get("enabled", False):
#                 logger.info("Bot disabled — waiting")
#                 time.sleep(5)
#                 continue

#             logger.info("Heartbeat — bot running")

#             for symbol in cfg["symbols"]:
#                 logger.info(f"Processing {symbol}")

#                 market = fetch_market_snapshot(symbol, cfg)

#                 if market is None:
#                     logger.warning(f"No market data for {symbol}")
#                     continue

#                 decision = evaluate_symbol(market, cfg)

#                 executor.handle_decision(decision)

#             time.sleep(cfg.get("loop_sleep", 10))

#         except Exception as e:
#             logger.exception(f"Main loop error: {e}")
#             time.sleep(5)


# if __name__ == "__main__":
#     main()



# import time

# from utils.logger import setup_logger
# from utils.config_loader import load_config

# from data.market_data import fetch_market_snapshot
# from strategy.strategy_engine import evaluate_symbol
# from trading.executor import Executor

# logger = setup_logger("main")


# def main():
#     logger.info("RevBot starting (paper mode default)")

#     cfg = load_config()
#     executor = Executor(cfg)

#     while True:
#         try:
#             cfg = load_config()  # hot reload

#             if not cfg.get("enabled", False):
#                 logger.info("Bot disabled — waiting")
#                 time.sleep(5)
#                 continue

#             logger.info("Heartbeat — bot running")

#             for symbol in cfg["symbols"]:
#                 logger.info(f"Processing {symbol}")

#                 market = fetch_market_snapshot(symbol)

#                 if not market:
#                     logger.warning(f"No market data for {symbol}")
#                     continue

#                 decision = evaluate_symbol(symbol, market, cfg)
#                 executor.handle_decision(decision)

#             time.sleep(cfg.get("loop_sleep", 10))

#         except Exception as e:
#             logger.exception(f"Main loop error: {e}")
#             time.sleep(5)


# if __name__ == "__main__":
#     main()


# import time

# from utils.logger import setup_logger
# from utils.config_loader import load_config

# from data.market_data import fetch_ohlcv
# from strategy.strategy_engine import evaluate_symbol
# from trading.executor import Executor

# logger = setup_logger()


# def main():
#     logger.info("🚀 RevBot starting (paper mode default)")

#     cfg = load_config()
#     executor = Executor(cfg)

#     while True:
#         try:
#             cfg = load_config()  # hot reload config

#             if not cfg.get("enabled", False):
#                 logger.info("⏸ Bot disabled — waiting...")
#                 time.sleep(5)
#                 continue

#             logger.info("❤️ Heartbeat — bot running")

#             for symbol in cfg["symbols"]:
#                 logger.info(f"🔍 Processing {symbol}")

#                 ohlcv = fetch_ohlcv(
#                     symbol=symbol,
#                     interval=cfg["interval"],
#                     limit=cfg["lookback"]
#                 )

#                 if not ohlcv:
#                     logger.warning(f"⚠️ No market data for {symbol}")
#                     continue

#                 decision = evaluate_symbol(symbol, ohlcv, cfg)

#                 executor.handle_decision(decision)

#             time.sleep(10)

#         except Exception as e:
#             logger.exception(f"🔥 Main loop error: {e}")
#             time.sleep(5)


# if __name__ == "__main__":
#     main()


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
