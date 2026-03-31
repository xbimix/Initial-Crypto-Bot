from __future__ import annotations

from collections import defaultdict, deque
from dataclasses import dataclass, field
from threading import RLock
from typing import Any


@dataclass(frozen=True)
class SnapshotMergeResult:
    symbol: str
    version: int
    state_changed: bool
    changed_fields: tuple[str, ...]
    field_timestamps: dict[str, float]
    quality_state: str


@dataclass(frozen=True)
class PriceHistoryResult:
    symbol: str
    history: list[dict[str, float]]
    history_version: int
    state_changed: bool


@dataclass
class SymbolSnapshotState:
    symbol: str
    version: int = 0
    quality_state: str = "UNKNOWN"
    latest_snapshot_ts: float | None = None
    fields: dict[str, Any] = field(default_factory=dict)
    field_timestamps: dict[str, float] = field(default_factory=dict)


@dataclass
class CandleSeriesState:
    symbol: str
    timeframe: str
    latest_open_time: int | None
    prices: list[float]
    weights: list[float]
    metadata: dict[str, Any]
    version: int
    refreshed_at_epoch: float


class MarketDataStateStore:
    """
    Canonical in-memory store for per-symbol runtime market state.
    """

    def __init__(self) -> None:
        self._lock = RLock()
        self._symbol_state: dict[str, SymbolSnapshotState] = {}
        self._price_history: dict[str, deque] = defaultdict(deque)
        self._price_history_version: dict[str, int] = {}
        self._candle_cache: dict[tuple[str, str], CandleSeriesState] = {}
        self._indicator_cache: dict[str, dict[str, Any]] = {}

    @property
    def legacy_price_history(self) -> dict[str, deque]:
        return self._price_history

    @property
    def legacy_indicator_cache(self) -> dict[str, dict[str, Any]]:
        return self._indicator_cache

    def clear(self) -> None:
        with self._lock:
            self._symbol_state.clear()
            self._price_history.clear()
            self._price_history_version.clear()
            self._candle_cache.clear()
            self._indicator_cache.clear()

    def merge_snapshot_fields(
        self,
        *,
        symbol: str,
        fields: dict[str, Any],
        snapshot_ts_epoch: float,
        quality_state: str,
    ) -> SnapshotMergeResult:
        sym = str(symbol or "").strip().upper()
        with self._lock:
            state = self._symbol_state.get(sym)
            if state is None:
                state = SymbolSnapshotState(symbol=sym)
                self._symbol_state[sym] = state

            state.version += 1
            state.latest_snapshot_ts = float(snapshot_ts_epoch)
            state.quality_state = str(quality_state or "UNKNOWN").strip().upper() or "UNKNOWN"

            changed: list[str] = []
            for key, value in fields.items():
                prior = state.fields.get(key, object())
                if prior != value:
                    state.fields[key] = value
                    state.field_timestamps[key] = float(snapshot_ts_epoch)
                    changed.append(key)
                elif key not in state.field_timestamps:
                    state.field_timestamps[key] = float(snapshot_ts_epoch)

            return SnapshotMergeResult(
                symbol=sym,
                version=state.version,
                state_changed=bool(changed),
                changed_fields=tuple(changed),
                field_timestamps=dict(state.field_timestamps),
                quality_state=state.quality_state,
            )

    def record_mark_price(
        self,
        *,
        symbol: str,
        snapshot_ts: float,
        mark_price: float,
        weight: float,
        history_seconds: int,
    ) -> PriceHistoryResult:
        sym = str(symbol or "").strip().upper()
        sample = {
            "ts": float(snapshot_ts),
            "price": float(mark_price),
            "weight": max(float(weight), 1.0),
        }
        with self._lock:
            history = self._price_history[sym]
            changed = False
            if history and abs(float(history[-1]["ts"]) - float(snapshot_ts)) < 1e-6:
                if history[-1] != sample:
                    history[-1] = sample
                    changed = True
            else:
                history.append(sample)
                changed = True

            cutoff = float(snapshot_ts) - float(history_seconds)
            while history and float(history[0]["ts"]) < cutoff:
                history.popleft()
                changed = True

            if changed:
                self._price_history_version[sym] = int(self._price_history_version.get(sym, 0) or 0) + 1
            history_version = int(self._price_history_version.get(sym, 0) or 0)
            return PriceHistoryResult(
                symbol=sym,
                history=list(history),
                history_version=history_version,
                state_changed=changed,
            )

    def get_candle_cache(self, *, symbol: str, timeframe: str) -> CandleSeriesState | None:
        key = (str(symbol or "").strip().upper(), str(timeframe or "").strip().lower())
        with self._lock:
            state = self._candle_cache.get(key)
            if state is None:
                return None
            return CandleSeriesState(
                symbol=state.symbol,
                timeframe=state.timeframe,
                latest_open_time=state.latest_open_time,
                prices=list(state.prices),
                weights=list(state.weights),
                metadata=dict(state.metadata),
                version=int(state.version),
                refreshed_at_epoch=float(state.refreshed_at_epoch),
            )

    def set_candle_cache(
        self,
        *,
        symbol: str,
        timeframe: str,
        latest_open_time: int | None,
        prices: list[float],
        weights: list[float],
        metadata: dict[str, Any],
        refreshed_at_epoch: float,
    ) -> CandleSeriesState:
        key = (str(symbol or "").strip().upper(), str(timeframe or "").strip().lower())
        with self._lock:
            prior = self._candle_cache.get(key)
            version = int(prior.version if prior is not None else 0) + 1
            state = CandleSeriesState(
                symbol=key[0],
                timeframe=key[1],
                latest_open_time=int(latest_open_time) if latest_open_time is not None else None,
                prices=list(prices),
                weights=list(weights),
                metadata=dict(metadata),
                version=version,
                refreshed_at_epoch=float(refreshed_at_epoch),
            )
            self._candle_cache[key] = state
            return CandleSeriesState(
                symbol=state.symbol,
                timeframe=state.timeframe,
                latest_open_time=state.latest_open_time,
                prices=list(state.prices),
                weights=list(state.weights),
                metadata=dict(state.metadata),
                version=int(state.version),
                refreshed_at_epoch=float(state.refreshed_at_epoch),
            )

    def get_indicator_features(self, *, cache_key: str, fingerprint: str) -> dict[str, Any] | None:
        with self._lock:
            entry = self._indicator_cache.get(cache_key)
            if not isinstance(entry, dict):
                return None
            if str(entry.get("fingerprint")) != str(fingerprint):
                return None
            features = entry.get("features")
            return dict(features) if isinstance(features, dict) else None

    def set_indicator_features(self, *, cache_key: str, fingerprint: str, features: dict[str, Any]) -> None:
        with self._lock:
            self._indicator_cache[cache_key] = {
                "fingerprint": str(fingerprint),
                "features": dict(features),
            }


MARKET_DATA_STATE_STORE = MarketDataStateStore()
