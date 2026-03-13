import logging
import os
import sys
from logging.handlers import RotatingFileHandler
from pathlib import Path

LOG_DIR = Path(__file__).resolve().parent.parent / "state"
LOG_DIR.mkdir(parents=True, exist_ok=True)
LOG_FILE = LOG_DIR / "bot.log"

_FILE_HANDLER_ADDED = False


class SafeRotatingFileHandler(RotatingFileHandler):
    """
    Windows-safe rotating handler.
    If another process holds the file lock during rollover, skip rotation
    instead of raising and breaking logging calls.
    """

    def doRollover(self):
        try:
            super().doRollover()
        except PermissionError:
            return
        except OSError:
            return


def _parse_int_env(name: str, default: int, *, minimum: int = 0) -> int:
    raw = os.getenv(name)
    if raw is None:
        return default
    try:
        value = int(raw)
    except ValueError:
        return default
    return max(value, minimum)


def _resolve_log_level() -> int:
    level_name = os.getenv("REVBOT_LOG_LEVEL", "INFO").strip().upper()
    return getattr(logging, level_name, logging.INFO)


def setup_logger(name: str = "revbot"):
    global _FILE_HANDLER_ADDED

    log_level = _resolve_log_level()
    logger = logging.getLogger(name)
    logger.setLevel(log_level)

    formatter = logging.Formatter("%(asctime)s | %(levelname)s | %(message)s")

    if not any(
        isinstance(handler, logging.StreamHandler)
        and not isinstance(handler, logging.FileHandler)
        for handler in logger.handlers
    ):
        console = logging.StreamHandler(sys.stdout)
        console.setFormatter(formatter)
        console.setLevel(log_level)
        logger.addHandler(console)

    if not _FILE_HANDLER_ADDED:
        max_bytes = _parse_int_env("REVBOT_LOG_MAX_BYTES", 5 * 1024 * 1024, minimum=1)
        backup_count = _parse_int_env("REVBOT_LOG_BACKUP_COUNT", 5, minimum=1)

        file_handler = SafeRotatingFileHandler(
            LOG_FILE,
            maxBytes=max_bytes,
            backupCount=backup_count,
            encoding="utf-8",
        )
        file_handler.setFormatter(formatter)
        file_handler.setLevel(log_level)

        root_logger = logging.getLogger()
        root_logger.addHandler(file_handler)
        root_logger.setLevel(log_level)
        _FILE_HANDLER_ADDED = True

    logger.propagate = True
    return logger
