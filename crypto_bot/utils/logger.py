import logging
import os
import sys
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import Iterable

LOG_DIR = Path(__file__).resolve().parent.parent / "state"
LOG_DIR.mkdir(parents=True, exist_ok=True)
LOG_FILE = LOG_DIR / "bot.log"

_FILE_HANDLER_ADDED = False
_CATEGORY_HANDLERS_ADDED = False

_CATEGORY_LOGGER_MAP = {
    "runtime": {
        "main",
        "config_loader",
        "market_data",
        "revolut_api",
        "revolut_auth",
        "revolut_balances",
        "revolut_orders",
        "revolut_order_book",
        "revolut_trades",
    },
    "strategy": {"strategy"},
    "risk": {"risk", "global_guard"},
    "trade": {"executor", "paper", "paper_trader"},
    "audit": {"control"},
}


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


class _LoggerNameFilter(logging.Filter):
    def __init__(self, logger_names: Iterable[str]):
        super().__init__()
        self._logger_names = tuple(
            str(name).strip()
            for name in logger_names
            if str(name).strip()
        )

    def filter(self, record: logging.LogRecord) -> bool:
        record_name = str(getattr(record, "name", "") or "")
        for name in self._logger_names:
            if record_name == name or record_name.startswith(f"{name}."):
                return True
        return False


def _env_bool(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    normalized = raw.strip().lower()
    if normalized in {"1", "true", "yes", "on"}:
        return True
    if normalized in {"0", "false", "no", "off"}:
        return False
    return default


def _add_category_handlers(root_logger: logging.Logger, formatter: logging.Formatter, log_level: int):
    global _CATEGORY_HANDLERS_ADDED

    if _CATEGORY_HANDLERS_ADDED:
        return

    if not _env_bool("REVBOT_LOG_CATEGORY_FILES", default=True):
        _CATEGORY_HANDLERS_ADDED = True
        return

    category_max_bytes = _parse_int_env(
        "REVBOT_LOG_CATEGORY_MAX_BYTES",
        2 * 1024 * 1024,
        minimum=1,
    )
    category_backup_count = _parse_int_env(
        "REVBOT_LOG_CATEGORY_BACKUP_COUNT",
        5,
        minimum=1,
    )

    for category, logger_names in _CATEGORY_LOGGER_MAP.items():
        file_path = LOG_DIR / f"bot.{category}.log"
        handler = SafeRotatingFileHandler(
            file_path,
            maxBytes=category_max_bytes,
            backupCount=category_backup_count,
            encoding="utf-8",
        )
        handler.setFormatter(formatter)
        handler.setLevel(log_level)
        handler.addFilter(_LoggerNameFilter(logger_names))
        root_logger.addHandler(handler)

    error_path = LOG_DIR / "bot.errors.log"
    error_handler = SafeRotatingFileHandler(
        error_path,
        maxBytes=category_max_bytes,
        backupCount=category_backup_count,
        encoding="utf-8",
    )
    error_handler.setFormatter(formatter)
    error_handler.setLevel(logging.ERROR)
    root_logger.addHandler(error_handler)

    _CATEGORY_HANDLERS_ADDED = True


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
        _add_category_handlers(root_logger, formatter, log_level)
        _FILE_HANDLER_ADDED = True

    logger.propagate = True
    return logger
