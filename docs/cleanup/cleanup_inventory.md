# Cleanup Inventory

Date: 2026-04-06

## Scope
Inventory of repository structure for safe cleanup and reorganization.

## Top-Level Classification
- KEEP: `.github/`, `crypto_bot/`, `web-ui/`, `scripts/`, `docs/`, `pytest.ini`, `.gitignore`, `AGENTS.MD`
- RUNTIME STATE (KEEP, IGNORED): `.runtime/`
- LOCAL ENV (KEEP LOCAL ONLY): `.venv/`
- TEMP/JUNK CANDIDATES: `.pytest_cache/`, `.tmp_*`, `.work_localcheck_*`, `work_testdirs*`
- ARTIFACT/NOTES MOVED: `DataQualityUpgrade.txt`, `DeploymentReadyStatus.txt`, `Upgrades.txt`, `repo_structure.txt` (archived under `docs/archive/notes/`)

## Current Hotspots
- `.runtime/state/` contains live logs, snapshots, db, and audit streams; do not purge blindly.
- `crypto_bot/state/` still exists for legacy fallback and currently overlaps runtime filenames.
- Temporary directories remain present but are blocked by Windows access locks.

## Immediate Cleanup Status
- Root note clutter relocated out of root.
- Cleanup protocol file normalized and tightened.
- Cleanup manifests initiated under `docs/cleanup/`.
