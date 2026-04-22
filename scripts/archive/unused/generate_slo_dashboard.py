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

from reporting.slo_dashboard import build_slo_dashboard, write_slo_dashboard


def _utc_today_iso() -> str:
    return datetime.now(timezone.utc).date().isoformat()


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Generate machine-readable SLO dashboard artifact.")
    parser.add_argument("--day", default=_utc_today_iso(), help="UTC day in YYYY-MM-DD format.")
    parser.add_argument("--output", default="", help="Optional output path for SLO dashboard JSON.")
    return parser


def main() -> int:
    parser = _build_parser()
    args = parser.parse_args()
    report = build_slo_dashboard(args.day)
    output_path = (
        write_slo_dashboard(report, output_path=Path(args.output))
        if args.output
        else write_slo_dashboard(report)
    )
    print(f"SLO dashboard generated: {output_path}")
    print(
        "summary: "
        f"freshness_ratio={report.get('freshness', {}).get('healthy_ratio', 0)} "
        f"blocked={report.get('gate_blocks', {}).get('total_blocked', 0)} "
        f"executions={report.get('execution', {}).get('executions_count', 0)} "
        f"expectancy={report.get('execution', {}).get('expectancy_per_closed_trade_usd', 0)}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

