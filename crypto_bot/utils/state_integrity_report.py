from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from utils.state_paths import (
    legacy_state_fallback_enabled,
    read_path_with_legacy_fallback,
    resolve_legacy_state_dir,
    resolve_legacy_state_file,
)


@dataclass(frozen=True)
class StateFileResolution:
    filename: str
    primary_path: str
    legacy_path: str
    resolved_path: str
    primary_exists: bool
    legacy_exists: bool
    used_legacy_fallback: bool
    collision_detected: bool
    collision_reason: str | None

    def as_dict(self) -> dict:
        return {
            "filename": self.filename,
            "primary_path": self.primary_path,
            "legacy_path": self.legacy_path,
            "resolved_path": self.resolved_path,
            "primary_exists": self.primary_exists,
            "legacy_exists": self.legacy_exists,
            "used_legacy_fallback": self.used_legacy_fallback,
            "collision_detected": self.collision_detected,
            "collision_reason": self.collision_reason,
        }


@dataclass(frozen=True)
class StateIntegrityReport:
    generated_at: str
    active_state_root: str
    legacy_state_root: str
    ok: bool
    collision_count: int
    used_legacy_count: int
    files: tuple[StateFileResolution, ...]

    def as_dict(self) -> dict:
        return {
            "generated_at": self.generated_at,
            "active_state_root": self.active_state_root,
            "legacy_state_root": self.legacy_state_root,
            "ok": self.ok,
            "collision_count": self.collision_count,
            "used_legacy_count": self.used_legacy_count,
            "files": [item.as_dict() for item in self.files],
        }


def _detect_collision(primary: Path, legacy: Path) -> tuple[bool, str | None]:
    if not primary.exists() or not legacy.exists():
        return False, None
    try:
        p_stat = primary.stat()
        l_stat = legacy.stat()
    except OSError:
        return True, "both_exist_stat_error"

    if int(l_stat.st_mtime) > int(p_stat.st_mtime):
        return True, "legacy_newer_than_primary"
    if int(l_stat.st_size) != int(p_stat.st_size):
        return True, "size_mismatch"
    return False, None


def build_state_integrity_report(
    *,
    default_state_dir: Path,
    active_state_dir: Path,
    required_filenames: tuple[str, ...] | list[str],
) -> StateIntegrityReport:
    rows: list[StateFileResolution] = []
    legacy_enabled = legacy_state_fallback_enabled()
    for filename in required_filenames:
        primary_path = active_state_dir / filename
        legacy_path = resolve_legacy_state_file(default_state_dir, filename)
        if legacy_enabled:
            resolved = read_path_with_legacy_fallback(primary_path, legacy_path, emit_warning=False)
            collision_detected, collision_reason = _detect_collision(primary_path, legacy_path)
            used_legacy_fallback = resolved == legacy_path and legacy_path.exists()
        else:
            resolved = primary_path
            collision_detected = False
            collision_reason = None
            used_legacy_fallback = False

        rows.append(
            StateFileResolution(
                filename=filename,
                primary_path=str(primary_path),
                legacy_path=str(legacy_path),
                resolved_path=str(resolved),
                primary_exists=primary_path.exists(),
                legacy_exists=legacy_path.exists(),
                used_legacy_fallback=used_legacy_fallback,
                collision_detected=collision_detected,
                collision_reason=collision_reason,
            )
        )

    collision_count = sum(1 for row in rows if row.collision_detected)
    used_legacy_count = sum(1 for row in rows if row.used_legacy_fallback)
    return StateIntegrityReport(
        generated_at=datetime.now(timezone.utc).isoformat(),
        active_state_root=str(active_state_dir),
        legacy_state_root=str(resolve_legacy_state_dir(default_state_dir)) if legacy_enabled else "disabled",
        ok=collision_count == 0,
        collision_count=int(collision_count),
        used_legacy_count=int(used_legacy_count),
        files=tuple(rows),
    )
