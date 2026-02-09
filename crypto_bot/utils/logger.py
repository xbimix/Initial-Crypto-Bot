import logging
import sys
from pathlib import Path

LOG_DIR = Path("state")
LOG_DIR.mkdir(exist_ok=True)

LOG_FILE = LOG_DIR / "bot.log"

# Global guard
_FILE_HANDLER_ADDED = False


def setup_logger(name="revbot"):
    global _FILE_HANDLER_ADDED

    logger = logging.getLogger(name)
    logger.setLevel(logging.INFO)

    formatter = logging.Formatter(
        "%(asctime)s | %(levelname)s | %(message)s"
    )

    # ---- Console handler ----
    if not any(isinstance(h, logging.StreamHandler) for h in logger.handlers):
        console = logging.StreamHandler(sys.stdout)
        console.setFormatter(formatter)
        console.setLevel(logging.INFO)
        logger.addHandler(console)

    # ---- File handler (add ONCE globally) ----
    if not _FILE_HANDLER_ADDED:
        file_handler = logging.FileHandler(LOG_FILE, encoding="utf-8")
        file_handler.setFormatter(formatter)
        file_handler.setLevel(logging.INFO)

        logging.getLogger().addHandler(file_handler)
        logging.getLogger().setLevel(logging.INFO)

        _FILE_HANDLER_ADDED = True

    # Prevent double logging via root
    logger.propagate = True

    return logger




# import logging
# import sys
# from pathlib import Path

# LOG_DIR = Path("state")
# LOG_DIR.mkdir(exist_ok=True)

# LOG_FILE = LOG_DIR / "bot.log"


# def setup_logger(name="revbot"):
#     logger = logging.getLogger(name)

#     if logger.handlers:
#         return logger  # prevent duplicate handlers

#     logger.setLevel(logging.INFO)

#     formatter = logging.Formatter(
#         "%(asctime)s | %(levelname)s | %(message)s"
#     )

#     # ---- Console handler (Windows safe, no emojis) ----
#     console = logging.StreamHandler(sys.stdout)
#     console.setFormatter(formatter)
#     console.setLevel(logging.INFO)

#     # ---- File handler ----
#     file_handler = logging.FileHandler(LOG_FILE, encoding="utf-8")
#     file_handler.setFormatter(formatter)
#     file_handler.setLevel(logging.INFO)

#     logger.addHandler(console)
#     logger.addHandler(file_handler)

#     return logger


# crypto_bot/
# │
# ├── main.py                     # Main controller script
# ├── config.py                   # Configuration and settings
# │
# ├── api/
# │   └── revolut_api.py         # RevolutX API integration layer (to be filled in later)
# │
# ├── data/
# │   └── market_data.py          # Handles fetching market data
# │
# ├── analysis/
# │   └── indicators.py          # Your indicator functions (RSI, MA, etc.)
# │
# ├── strategy/
# │   └── strategy_engine.py      # Where we generate buy/sell signals
# │
# ├── trading/
# │   └── trader.py               # Manages actual trade decisions
# │
# └── utils/
#     └── logger.py               # (Optional) Logging and debugging utilities
