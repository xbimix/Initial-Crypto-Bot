import logging
import sys
from pathlib import Path

LOG_DIR = Path("state")
LOG_DIR.mkdir(exist_ok=True)

LOG_FILE = LOG_DIR / "bot.log"


def setup_logger():
    logger = logging.getLogger("RevBot")
    logger.setLevel(logging.INFO)

    if logger.handlers:
        return logger

    formatter = logging.Formatter(
        "%(asctime)s | %(levelname)s | %(message)s"
    )

    # File handler (UTF-8 safe)
    file_handler = logging.FileHandler(LOG_FILE, encoding="utf-8")
    file_handler.setFormatter(formatter)

    # Console handler (force UTF-8)
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setFormatter(formatter)

    logger.addHandler(file_handler)
    logger.addHandler(console_handler)

    return logger


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
