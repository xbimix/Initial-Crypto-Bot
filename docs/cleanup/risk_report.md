# Risk Report

Date: 2026-04-06

## Primary Risks
1. Runtime state ambiguity between `.runtime/state/` and `crypto_bot/state/`.
2. Accidental deletion of fallback files that are still read in compatibility mode.
3. Windows file locks preventing deterministic cleanup of temp folders.

## Mitigations Applied
- No runtime behavior changes in this cleanup pass.
- No deletion of runtime or legacy state files.
- Added explicit manifests before deletion.

## Remaining Risk
- Temp/cache clutter remains until locks are released.
- Legacy/runtime overlap still requires explicit migration completion pass.
