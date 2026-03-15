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

from reporting.weekly_summary import build_weekly_summary, write_weekly_summary


def _utc_today_iso() -> str:
    return datetime.now(timezone.utc).date().isoformat()


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Generate weekly operational summary from daily report artifacts.",
    )
    parser.add_argument(
        "--end-day",
        default=_utc_today_iso(),
        help="UTC end day in YYYY-MM-DD format (default: today UTC).",
    )
    parser.add_argument(
        "--days",
        type=int,
        default=7,
        help="Number of UTC days to include (default: 7).",
    )
    parser.add_argument(
        "--output",
        default="",
        help="Optional output path override.",
    )
    return parser


def main() -> int:
    args = _parser().parse_args()
    report = build_weekly_summary(args.end_day, day_count=args.days)
    output_path = (
        write_weekly_summary(report, output_path=Path(args.output))
        if args.output
        else write_weekly_summary(report)
    )

    summary = report.get("summary", {})
    window = report.get("window", {})
    anomalies = report.get("anomaly_notes", [])
    print(f"Weekly summary generated: {output_path}")
    print(
        "window: "
        f"{window.get('start_day_utc')}..{window.get('end_day_utc')} "
        f"available={window.get('available_day_count')} "
        f"missing={len(window.get('missing_days', [])) if isinstance(window.get('missing_days'), list) else 0}"
    )
    print(
        "summary: "
        f"realized_total={summary.get('realized_pnl_total_usd', 0)} "
        f"latest_unrealized={summary.get('latest_unrealized_pnl_usd', 0)} "
        f"latest_net={summary.get('latest_net_paper_pnl_usd', 0)} "
        f"restarts={summary.get('restart_count_total', 0)} "
        f"crashes={summary.get('crash_count_total', 0)}"
    )
    print(f"anomalies: {len(anomalies) if isinstance(anomalies, list) else 0}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
