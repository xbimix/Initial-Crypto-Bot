from __future__ import annotations

from collections import defaultdict, deque
from typing import Deque


class CandleCache:
    def __init__(self, max_points_per_key: int = 5000):
        self.max_points_per_key = int(max_points_per_key)
        self._cache: dict[tuple[str, str], Deque[dict]] = defaultdict(deque)

    def update(self, symbol: str, timeframe: str, candles: list[dict]) -> None:
        key = (str(symbol).upper(), str(timeframe).lower())
        buf = self._cache[key]
        for row in candles:
            buf.append(dict(row))
        while len(buf) > self.max_points_per_key:
            buf.popleft()

    def get(self, symbol: str, timeframe: str, limit: int | None = None) -> list[dict]:
        key = (str(symbol).upper(), str(timeframe).lower())
        rows = list(self._cache.get(key, deque()))
        if limit is None:
            return rows
        return rows[-int(limit):]

    def clear(self, symbol: str | None = None, timeframe: str | None = None) -> None:
        if symbol is None and timeframe is None:
            self._cache.clear()
            return
        symbol_norm = str(symbol).upper() if symbol is not None else None
        tf_norm = str(timeframe).lower() if timeframe is not None else None
        for key in list(self._cache.keys()):
            if symbol_norm is not None and key[0] != symbol_norm:
                continue
            if tf_norm is not None and key[1] != tf_norm:
                continue
            self._cache.pop(key, None)

