from __future__ import annotations

from dataclasses import dataclass


QUALITY_GOOD = "GOOD"
QUALITY_PARTIAL = "PARTIAL"
QUALITY_INSUFFICIENT = "INSUFFICIENT"
QUALITY_STALE = "STALE"
QUALITY_UNSUPPORTED_WINDOW = "UNSUPPORTED_WINDOW"


@dataclass
class QualityInput:
    sample_count: int
    min_required: int
    stale: bool = False
    supported: bool = True
    reason: str | None = None


def resolve_quality(payload: QualityInput) -> dict:
    if not payload.supported:
        return {
            "status": QUALITY_UNSUPPORTED_WINDOW,
            "reason": payload.reason or "window_not_supported",
            "sample_counts": {"observed": int(payload.sample_count), "required": int(payload.min_required)},
        }
    if payload.stale:
        return {
            "status": QUALITY_STALE,
            "reason": payload.reason or "stale_data",
            "sample_counts": {"observed": int(payload.sample_count), "required": int(payload.min_required)},
        }
    if payload.sample_count <= 0:
        return {
            "status": QUALITY_INSUFFICIENT,
            "reason": payload.reason or "no_samples",
            "sample_counts": {"observed": int(payload.sample_count), "required": int(payload.min_required)},
        }
    if payload.sample_count < payload.min_required:
        return {
            "status": QUALITY_PARTIAL,
            "reason": payload.reason or "partial_coverage",
            "sample_counts": {"observed": int(payload.sample_count), "required": int(payload.min_required)},
        }
    return {
        "status": QUALITY_GOOD,
        "reason": payload.reason or "ok",
        "sample_counts": {"observed": int(payload.sample_count), "required": int(payload.min_required)},
    }

