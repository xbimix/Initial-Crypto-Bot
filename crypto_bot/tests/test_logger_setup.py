from __future__ import annotations

import subprocess
import sys
from pathlib import Path


def _run_logger_probe(tmp_dir: Path, *, category_files: bool):
    script = f"""
import logging
import sys
from pathlib import Path

sys.path.insert(0, r"{str((Path(__file__).resolve().parents[1]).as_posix())}")
from utils import logger as rev_logger

rev_logger.LOG_DIR = Path(r"{str(tmp_dir.as_posix())}")
rev_logger.LOG_DIR.mkdir(parents=True, exist_ok=True)
rev_logger.LOG_FILE = rev_logger.LOG_DIR / "bot.log"
rev_logger._FILE_HANDLER_ADDED = False
rev_logger._CATEGORY_HANDLERS_ADDED = False

if {str(category_files)}:
    import os
    os.environ["REVBOT_LOG_CATEGORY_FILES"] = "1"
else:
    import os
    os.environ["REVBOT_LOG_CATEGORY_FILES"] = "0"

runtime = rev_logger.setup_logger("main")
strategy = rev_logger.setup_logger("strategy")
risk = rev_logger.setup_logger("risk")
trade = rev_logger.setup_logger("executor")
audit = rev_logger.setup_logger("control")

runtime.info("runtime_ok")
strategy.info("strategy_ok")
risk.info("risk_ok")
trade.info("trade_ok")
audit.info("audit_ok")
strategy.error("strategy_error")

logging.shutdown()
"""

    return subprocess.run(
        [sys.executable, "-c", script],
        check=False,
        capture_output=True,
        text=True,
    )


def test_category_log_files_enabled(tmp_path: Path):
    result = _run_logger_probe(tmp_path / "enabled", category_files=True)
    assert result.returncode == 0, result.stderr

    base_log = tmp_path / "enabled" / "bot.log"
    assert base_log.exists()
    assert "runtime_ok" in base_log.read_text(encoding="utf-8")

    runtime_log = tmp_path / "enabled" / "bot.runtime.log"
    strategy_log = tmp_path / "enabled" / "bot.strategy.log"
    risk_log = tmp_path / "enabled" / "bot.risk.log"
    trade_log = tmp_path / "enabled" / "bot.trade.log"
    audit_log = tmp_path / "enabled" / "bot.audit.log"
    errors_log = tmp_path / "enabled" / "bot.errors.log"

    assert runtime_log.exists()
    assert strategy_log.exists()
    assert risk_log.exists()
    assert trade_log.exists()
    assert audit_log.exists()
    assert errors_log.exists()

    assert "runtime_ok" in runtime_log.read_text(encoding="utf-8")
    assert "strategy_ok" in strategy_log.read_text(encoding="utf-8")
    assert "risk_ok" in risk_log.read_text(encoding="utf-8")
    assert "trade_ok" in trade_log.read_text(encoding="utf-8")
    assert "audit_ok" in audit_log.read_text(encoding="utf-8")
    assert "strategy_error" in errors_log.read_text(encoding="utf-8")


def test_category_log_files_can_be_disabled(tmp_path: Path):
    result = _run_logger_probe(tmp_path / "disabled", category_files=False)
    assert result.returncode == 0, result.stderr

    base_log = tmp_path / "disabled" / "bot.log"
    assert base_log.exists()
    assert "runtime_ok" in base_log.read_text(encoding="utf-8")

    assert not (tmp_path / "disabled" / "bot.runtime.log").exists()
    assert not (tmp_path / "disabled" / "bot.strategy.log").exists()
    assert not (tmp_path / "disabled" / "bot.risk.log").exists()
    assert not (tmp_path / "disabled" / "bot.trade.log").exists()
    assert not (tmp_path / "disabled" / "bot.audit.log").exists()
    assert not (tmp_path / "disabled" / "bot.errors.log").exists()
