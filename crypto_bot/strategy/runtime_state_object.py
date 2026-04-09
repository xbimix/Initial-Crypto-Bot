from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass
class StrategyRuntimeScalars:
    synced: bool = False
    last_paper_state_mtime: float | None = None
    metrics_dirty: bool = False
    last_metrics_flush_at: float = 0.0

    @classmethod
    def from_runtime_module(cls, runtime_module: Any) -> "StrategyRuntimeScalars":
        state = cls()
        state.hydrate_from_runtime(runtime_module)
        return state

    def hydrate_from_runtime(self, runtime_module: Any) -> None:
        self.synced = bool(getattr(runtime_module, "_synced", False))
        self.last_paper_state_mtime = getattr(runtime_module, "_last_paper_state_mtime", None)
        self.metrics_dirty = bool(getattr(runtime_module, "_metrics_dirty", False))
        self.last_metrics_flush_at = float(getattr(runtime_module, "_last_metrics_flush_at", 0.0) or 0.0)

    def persist_to_runtime(self, runtime_module: Any) -> None:
        runtime_module._synced = bool(self.synced)
        runtime_module._last_paper_state_mtime = self.last_paper_state_mtime
        runtime_module._metrics_dirty = bool(self.metrics_dirty)
        runtime_module._last_metrics_flush_at = float(self.last_metrics_flush_at)


class StrategyRuntimeState:
    """
    Thin runtime-state adapter used by orchestration hot paths.

    It presents a single object contract while preserving backward
    compatibility with the existing `strategy_runtime_state` module fields.
    """

    def __init__(self, runtime_module: Any):
        object.__setattr__(self, "_runtime_module", runtime_module)
        object.__setattr__(
            self,
            "scalars",
            StrategyRuntimeScalars.from_runtime_module(runtime_module),
        )

    @classmethod
    def from_runtime_module(cls, runtime_module: Any) -> "StrategyRuntimeState":
        return cls(runtime_module)

    def hydrate_from_runtime(self) -> None:
        self.scalars.hydrate_from_runtime(self._runtime_module)

    def persist_to_runtime(self) -> None:
        self.scalars.persist_to_runtime(self._runtime_module)

    @property
    def synced(self) -> bool:
        return bool(self.scalars.synced)

    @synced.setter
    def synced(self, value: bool) -> None:
        self.scalars.synced = bool(value)
        self.persist_to_runtime()

    @property
    def last_paper_state_mtime(self):
        return self.scalars.last_paper_state_mtime

    @last_paper_state_mtime.setter
    def last_paper_state_mtime(self, value) -> None:
        self.scalars.last_paper_state_mtime = value
        self.persist_to_runtime()

    def __getattr__(self, name: str):
        # Delegate mutable map state to the runtime module so existing
        # callers continue to operate on the canonical dictionaries.
        return getattr(self._runtime_module, name)

    def __setattr__(self, name: str, value: Any) -> None:
        if name in {"_runtime_module", "scalars"}:
            object.__setattr__(self, name, value)
            return
        setattr(self._runtime_module, name, value)
