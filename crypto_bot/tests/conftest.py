from __future__ import annotations

import shutil
import sys
import uuid
from pathlib import Path

import pytest


PROJECT_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = Path(__file__).resolve().parents[2]
TEST_WORK_ROOT = REPO_ROOT / "work_testdirs"

if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


@pytest.fixture
def tmp_path() -> Path:
    TEST_WORK_ROOT.mkdir(parents=True, exist_ok=True)
    case_dir = TEST_WORK_ROOT / f"case_{uuid.uuid4().hex}"
    case_dir.mkdir(parents=True, exist_ok=True)
    try:
        yield case_dir
    finally:
        shutil.rmtree(case_dir, ignore_errors=True)
