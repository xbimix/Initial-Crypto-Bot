from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[1]


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Run strategy replay regression against captured fixture cases.",
    )
    parser.add_argument(
        "--fixture",
        default=str(_repo_root() / "crypto_bot" / "tests" / "fixtures" / "strategy_replay_cases.json"),
        help="Path to strategy replay fixture JSON",
    )
    parser.add_argument(
        "--output",
        default=str(_repo_root() / "crypto_bot" / "state" / "reports" / "strategy_replay_latest.json"),
        help="Path to write replay comparison output",
    )
    args = parser.parse_args()

    repo_root = _repo_root()
    crypto_bot_root = repo_root / "crypto_bot"
    if str(crypto_bot_root) not in sys.path:
        sys.path.insert(0, str(crypto_bot_root))

    from utils.strategy_replay import run_replay_fixture

    report = run_replay_fixture(
        fixture_path=Path(args.fixture),
        output_path=Path(args.output),
    )

    print(
        json.dumps(
            {
                "fixture": report.get("fixture_path"),
                "case_count": report.get("case_count"),
                "matched_count": report.get("matched_count"),
                "mismatch_count": report.get("mismatch_count"),
                "output": args.output,
            },
            indent=2,
        )
    )

    mismatches = report.get("mismatches", [])
    if mismatches:
        print("\nTop mismatches:")
        for item in mismatches[:20]:
            print(json.dumps(item, indent=2))
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
