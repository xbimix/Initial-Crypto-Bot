import logging
from logging.handlers import RotatingFileHandler
from pathlib import Path

LOG_DIR = Path("state")
LOG_DIR.mkdir(exist_ok=True)

LOG_FILE = LOG_DIR / "bot.log"

def setup_logger(name="RevBot"):
    logger = logging.getLogger(name)
    logger.setLevel(logging.INFO)

    formatter = logging.Formatter(
        "%(asctime)s | %(levelname)s | %(message)s"
    )

    file_handler = RotatingFileHandler(
        LOG_FILE, maxBytes=5_000_000, backupCount=5
    )
    file_handler.setFormatter(formatter)

    console_handler = logging.StreamHandler()
    console_handler.setFormatter(formatter)

    if not logger.handlers:
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
