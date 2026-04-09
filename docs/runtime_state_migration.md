# Runtime State Migration

## What changed
- Runtime-generated bot state is now rooted under `BOT_DATA_DIR`.
- Default runtime root is `.runtime/` at repo root.
- State files resolve to `.runtime/state/` by default (for example: `.runtime/state/config.json`, `.runtime/state/paper_state.json`).
- Legacy override `REVBOT_STATE_DIR` is still supported and has priority when set.

## Backward compatibility
- If a file is missing in the new runtime location but exists in the legacy state path (`crypto_bot/state` or `REVBOT_STATE_DIR`), RevBot reads the legacy file as a fallback.
- For key mutable files (`config.json`, `paper_state.json`, `trades.json`), RevBot seeds/copies from legacy location into the new runtime location on first use.
- Legacy fallback reads now emit explicit warnings (`state_paths` logger in Python, `[revbot-state]` warning in UI fallback layer) so operators can see when migration is incomplete.

## Operator actions
1. Optional (recommended): set `BOT_DATA_DIR` explicitly for deployments.
2. Keep existing `REVBOT_STATE_DIR` only if you intentionally want legacy behavior.
3. Verify runtime writes now appear under `.runtime/state/` (or your configured `BOT_DATA_DIR`).
4. Remove tracked legacy runtime files from git index:
   - `pwsh ./scripts/untrack_runtime_state.ps1 -Apply`
5. Baseline/replay historical artifacts previously under `crypto_bot/state/baseline` are now archived under `docs/archive/state_baseline/`.

## Notes
- Existing filenames are unchanged; only the base directory moved.
- `.gitignore` now ignores `.runtime/`, `var/`, and legacy runtime state directories to avoid committing mutable artifacts.
- Runtime housekeeping now includes size-based JSONL pruning for large operational streams (`decision_audit.jsonl`, `market_sync_health_history.jsonl`, `ingestion_freshness_history.jsonl`, `runtime_events.jsonl`, `audit_actions.jsonl`).
