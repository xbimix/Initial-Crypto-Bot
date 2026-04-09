from __future__ import annotations

import json
from pathlib import Path


def test_behavior_lock_baseline_contains_required_files():
    repo_root = Path(__file__).resolve().parents[2]
    baseline_path = repo_root / "crypto_bot" / "strategy" / "strategy_hash_baseline.json"
    assert baseline_path.exists()

    payload = json.loads(baseline_path.read_text(encoding="utf-8-sig"))
    files = payload.get("files", {})
    assert isinstance(files, dict)

    required = {
        "crypto_bot/main.py",
        "crypto_bot/strategy/regime_router.py",
        "crypto_bot/strategy/strategy_engine.py",
    }
    missing = sorted(required.difference(files.keys()))
    assert not missing, f"missing required behavior-lock files: {missing}"
