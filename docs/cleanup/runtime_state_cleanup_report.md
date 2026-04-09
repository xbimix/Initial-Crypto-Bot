# Runtime State Cleanup Report

## Scope
- Keep runtime behavior unchanged while reducing state-path ambiguity.
- Remove legacy runtime files from source control tracking.
- Keep fallback reads temporarily, but make fallback usage visible.

## Applied Changes
- Legacy fallback reads now emit explicit one-time warnings:
  - Python: `utils.state_paths.read_path_with_legacy_fallback(...)`
  - Web UI fallback API: `web-ui/src/app/api/_lib/stateFallback.ts`
- Runtime housekeeping now prunes oversized JSONL streams by size:
  - `decision_audit.jsonl`
  - `market_sync_health_history.jsonl`
  - `ingestion_freshness_history.jsonl`
  - `runtime_events.jsonl`
  - `audit_actions.jsonl`
- Legacy tracked `crypto_bot/state/*` files were removed from git index (`git rm --cached -r crypto_bot/state`).
- Historical baseline artifacts were relocated from `crypto_bot/state/baseline/` to `docs/archive/state_baseline/`.

## Validation
- Targeted tests passed:
  - `crypto_bot/tests/test_state_paths.py`
  - `crypto_bot/tests/test_runtime_guard.py`
  - `crypto_bot/tests/test_main_runtime.py`

## Remaining Manual/Operational Items
- Two ACL-locked legacy directories may still need admin cleanup on some machines:
  - `crypto_bot/state/pytest_base_env`
  - `crypto_bot/state/tmpbz5d4cs7`
- Helper script added:
  - `scripts/cleanup_locked_legacy_state_dirs.ps1`
