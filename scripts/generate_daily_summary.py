from __future__ import annotations

import argparse
import sys
from datetime import datetime, timezone
from pathlib import Path


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[1]


CRYPTO_BOT_ROOT = _repo_root() / "crypto_bot"
if str(CRYPTO_BOT_ROOT) not in sys.path:
    sys.path.insert(0, str(CRYPTO_BOT_ROOT))

from reporting.daily_summary import build_daily_summary, write_daily_summary


def _utc_today_iso() -> str:
    return datetime.now(timezone.utc).date().isoformat()


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Generate a daily paper-trading summary report."
    )
    parser.add_argument(
        "--day",
        default=_utc_today_iso(),
        help="UTC day in YYYY-MM-DD format (default: today UTC).",
    )
    parser.add_argument(
        "--output",
        default="",
        help="Optional output path for report JSON.",
    )
    return parser


def main() -> int:
    parser = _build_parser()
    args = parser.parse_args()

    report = build_daily_summary(args.day)
    output_path = (
        write_daily_summary(report, output_path=Path(args.output))
        if args.output
        else write_daily_summary(report)
    )

    summary = report.get("summary", {})
    run_quality = report.get("run_quality", {})
    print(f"Daily summary generated: {output_path}")
    print(
        "summary: "
        f"buys={summary.get('total_buys', 0)} "
        f"sells={summary.get('total_sells', 0)} "
        f"realized={summary.get('realized_pnl_usd', 0)} "
        f"unrealized={summary.get('unrealized_pnl_usd', 0)} "
        f"net={summary.get('net_paper_pnl_usd', 0)}"
    )
    print(
        "run_quality: "
        f"crashes={run_quality.get('crash_count', 0)} "
        f"restarts={run_quality.get('restart_count', 0)} "
        f"stale_data_blocks={run_quality.get('stale_data_blocks', 0)}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
