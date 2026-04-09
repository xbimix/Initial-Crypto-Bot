from __future__ import annotations

from pathlib import Path

from data import revolut_market_db


class RevolutCandleStore:
    def __init__(self, db_path: str | Path | None = None):
        self.db_path = db_path
        revolut_market_db.ensure_schema(self.db_path)

    def upsert(
        self,
        symbol: str,
        timeframe: str,
        candles: list[dict],
        *,
        source: str = "revolut",
        max_rows: int | None = None,
    ) -> int:
        inserted = revolut_market_db.upsert_candles(
            symbol=symbol,
            timeframe=timeframe,
            candles=candles,
            db_path=self.db_path,
            source=source,
        )
        if max_rows is not None and int(max_rows) > 0:
            revolut_market_db.trim_candles_to_limit(
                symbol=symbol,
                timeframe=timeframe,
                max_rows=int(max_rows),
                db_path=self.db_path,
            )
        return inserted

    def get_latest_open_time(self, symbol: str, timeframe: str) -> int | None:
        return revolut_market_db.get_latest_open_time(
            symbol=symbol,
            timeframe=timeframe,
            db_path=self.db_path,
        )

    def get_earliest_open_time(self, symbol: str, timeframe: str) -> int | None:
        return revolut_market_db.get_earliest_open_time(
            symbol=symbol,
            timeframe=timeframe,
            db_path=self.db_path,
        )

    def get_candles(
        self,
        symbol: str,
        timeframe: str,
        *,
        limit: int | None = None,
        ascending: bool = True,
    ) -> list[dict]:
        return revolut_market_db.get_candles(
            symbol=symbol,
            timeframe=timeframe,
            db_path=self.db_path,
            limit=limit,
            ascending=ascending,
        )

    def get_count(self, symbol: str, timeframe: str) -> int:
        return revolut_market_db.get_candle_count(
            symbol=symbol,
            timeframe=timeframe,
            db_path=self.db_path,
        )

    def get_last_updated_at(self, symbol: str, timeframe: str) -> int | None:
        return revolut_market_db.get_last_updated_at(
            symbol=symbol,
            timeframe=timeframe,
            db_path=self.db_path,
        )

    def trim_to_lookback_days(self, symbol: str, timeframe: str, lookback_days: int) -> int:
        return revolut_market_db.trim_candles_to_lookback_days(
            symbol=symbol,
            timeframe=timeframe,
            lookback_days=lookback_days,
            db_path=self.db_path,
        )

    def get_sync_state(self, symbol: str, timeframe: str) -> dict | None:
        return revolut_market_db.get_sync_state(
            symbol=symbol,
            timeframe=timeframe,
            db_path=self.db_path,
        )

    def list_sync_states(
        self,
        *,
        symbols: list[str] | None = None,
        timeframes: list[str] | None = None,
    ) -> list[dict]:
        return revolut_market_db.list_sync_states(
            symbols=symbols,
            timeframes=timeframes,
            db_path=self.db_path,
        )

    def upsert_sync_state(
        self,
        *,
        symbol: str,
        timeframe: str,
        earliest_ms: int | None,
        latest_ms: int | None,
        last_sync_ms: int | None,
        status: str,
        note: str = "",
    ) -> None:
        revolut_market_db.upsert_sync_state(
            symbol=symbol,
            timeframe=timeframe,
            earliest_ms=earliest_ms,
            latest_ms=latest_ms,
            last_sync_ms=last_sync_ms,
            status=status,
            note=note,
            db_path=self.db_path,
        )

    def find_missing_ranges(
        self,
        *,
        symbol: str,
        timeframe: str,
        target_start_ms: int,
        target_end_ms: int,
    ) -> list[tuple[int, int]]:
        return revolut_market_db.find_missing_ranges(
            symbol=symbol,
            timeframe=timeframe,
            target_start_ms=target_start_ms,
            target_end_ms=target_end_ms,
            db_path=self.db_path,
        )

    def delete_symbol_timeframe(self, *, symbol: str, timeframe: str) -> int:
        return revolut_market_db.delete_candles_for_symbol_timeframe(
            symbol=symbol,
            timeframe=timeframe,
            db_path=self.db_path,
        )

    def delete_sync_state(self, *, symbol: str, timeframe: str) -> int:
        return revolut_market_db.delete_sync_state(
            symbol=symbol,
            timeframe=timeframe,
            db_path=self.db_path,
        )
