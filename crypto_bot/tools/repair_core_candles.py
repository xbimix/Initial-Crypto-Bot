from __future__ import annotations

import argparse
import json
import time
from collections import defaultdict
import sys
from pathlib import Path

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from data.revolut_candle_store import RevolutCandleStore
from data.revolut_incremental_sync import sync_new_candles
from data.revolut_market_db import connect, resolve_db_path
from utils.state_io import read_json_file
from utils.state_paths import resolve_state_dir


CORE_TIMEFRAMES = ("1h", "4h", "1d")


def _latest_candles_by_timeframe(db_path: Path, timeframe: str) -> list[dict]:
    with connect(db_path) as conn:
        rows = conn.execute(
            """
            SELECT c.symbol, c.timeframe, c.open_time, c.open, c.high, c.low, c.close
            FROM candles c
            INNER JOIN (
                SELECT symbol, timeframe, MAX(open_time) AS max_open_time
                FROM candles
                WHERE timeframe = ?
                GROUP BY symbol, timeframe
            ) m
              ON c.symbol = m.symbol
             AND c.timeframe = m.timeframe
             AND c.open_time = m.max_open_time
            WHERE c.timeframe = ?
            ORDER BY c.symbol
            """,
            (timeframe, timeframe),
        ).fetchall()
    return [dict(row) for row in rows]


def detect_contamination(db_path: Path, *, duplicate_threshold: int = 3) -> dict[str, list[str]]:
    contaminated: dict[str, set[str]] = {tf: set() for tf in CORE_TIMEFRAMES}
    for timeframe in CORE_TIMEFRAMES:
        latest_rows = _latest_candles_by_timeframe(db_path, timeframe)
        by_ohlc: dict[tuple[float, float, float, float], list[str]] = defaultdict(list)
        for row in latest_rows:
            key = (
                round(float(row.get("open", 0.0) or 0.0), 8),
                round(float(row.get("high", 0.0) or 0.0), 8),
                round(float(row.get("low", 0.0) or 0.0), 8),
                round(float(row.get("close", 0.0) or 0.0), 8),
            )
            by_ohlc[key].append(str(row.get("symbol", "")).upper())
        for symbols in by_ohlc.values():
            uniq = [s for s in symbols if s]
            if len(uniq) >= duplicate_threshold:
                contaminated[timeframe].update(uniq)
    return {tf: sorted(list(symbols)) for tf, symbols in contaminated.items() if symbols}


def _tracked_symbols(state_dir: Path) -> list[str]:
    cfg = read_json_file(state_dir / "config.json", default={})
    if not isinstance(cfg, dict):
        return []
    raw = cfg.get("symbols", [])
    if not isinstance(raw, list):
        return []
    out: list[str] = []
    seen: set[str] = set()
    for item in raw:
        symbol = str(item or "").strip().upper()
        if not symbol or symbol in seen:
            continue
        seen.add(symbol)
        out.append(symbol)
    return out


def purge_and_rebuild(
    *,
    db_path: Path,
    state_dir: Path,
    contaminated: dict[str, list[str]],
    dry_run: bool = False,
) -> dict:
    store = RevolutCandleStore(db_path=db_path)
    tracked = set(_tracked_symbols(state_dir))
    removed_rows = 0
    removed_sync_rows = 0
    rebuild_rows: list[dict] = []

    for timeframe, symbols in contaminated.items():
        for symbol in symbols:
            if tracked and symbol not in tracked:
                continue
            if dry_run:
                rebuild_rows.append(
                    {
                        "symbol": symbol,
                        "timeframe": timeframe,
                        "status": "dry_run",
                    }
                )
                continue
            removed_rows += store.delete_symbol_timeframe(symbol=symbol, timeframe=timeframe)
            removed_sync_rows += store.delete_sync_state(symbol=symbol, timeframe=timeframe)
            try:
                result = sync_new_candles(
                    symbol=symbol,
                    timeframe=timeframe,
                    db_path=db_path,
                    include_partial=False,
                    now_ms=int(time.time() * 1000),
                )
                rebuild_rows.append(
                    {
                        "symbol": symbol,
                        "timeframe": timeframe,
                        "status": str(result.get("status", "ok")),
                        "requests": int(result.get("requests", 0) or 0),
                        "inserted": int(result.get("inserted", 0) or 0),
                        "new_inserted": int(result.get("new_inserted", 0) or 0),
                        "note": str(result.get("note") or ""),
                    }
                )
            except Exception as exc:
                rebuild_rows.append(
                    {
                        "symbol": symbol,
                        "timeframe": timeframe,
                        "status": "error",
                        "error": str(exc),
                    }
                )

    return {
        "removed_rows": int(removed_rows),
        "removed_sync_rows": int(removed_sync_rows),
        "rebuild": rebuild_rows,
    }


def _default_state_dir() -> Path:
    return resolve_state_dir(Path(__file__).resolve().parents[1] / "state")


def main() -> int:
    parser = argparse.ArgumentParser(description="Detect/repair contaminated core candles (1h/4h/1d).")
    parser.add_argument("--state-dir", default=str(_default_state_dir()))
    parser.add_argument("--db-path", default=None)
    parser.add_argument("--duplicate-threshold", type=int, default=3)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    state_dir = Path(args.state_dir)
    db_path = resolve_db_path(args.db_path)

    contaminated = detect_contamination(
        db_path,
        duplicate_threshold=max(2, int(args.duplicate_threshold)),
    )
    result = {
        "db_path": str(db_path),
        "contaminated": contaminated,
    }
    if contaminated:
        result["repair"] = purge_and_rebuild(
            db_path=db_path,
            state_dir=state_dir,
            contaminated=contaminated,
            dry_run=bool(args.dry_run),
        )
    else:
        result["repair"] = {"removed_rows": 0, "removed_sync_rows": 0, "rebuild": []}
    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
