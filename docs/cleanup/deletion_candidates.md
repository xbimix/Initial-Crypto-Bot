# Deletion Candidates

Date: 2026-04-06

## High Confidence (Generated Temp Only)
- `.pytest_cache/`
- `.tmp_check_local_pytest_9400/`
- `.tmp_pytest_codex/`
- `.tmp_pytest_phase_a/`
- `.tmp_replay/`
- `.work_localcheck_3036/`
- `work_localcheck_23076/`
- `work_testdirs/`
- `work_testdirs_probe/`

Reason: pytest/tooling generated work dirs and temp outputs.

## Status
All high-confidence temp candidates above were removed in the forced cleanup pass.

## Not Candidates In This Pass
- `.runtime/state/` (live runtime state)
- `crypto_bot/state/` (legacy fallback path; requires migration-aware cleanup)
- any code/test/doc files
