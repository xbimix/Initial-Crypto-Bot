from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class SnapshotFailure(Exception):
    symbol: str
    code: str
    stage: str
    message: str
    details: dict[str, Any] = field(default_factory=dict)

    def __str__(self) -> str:
        return f"{self.stage}:{self.code}:{self.message}"


def failure_payload(failure: SnapshotFailure) -> dict[str, Any]:
    return {
        "symbol": str(failure.symbol or "").strip().upper(),
        "code": str(failure.code or "").strip().lower(),
        "stage": str(failure.stage or "").strip().lower(),
        "message": str(failure.message or "").strip(),
        "details": dict(failure.details or {}),
    }

