# Runtime State Migration

## What changed
- Runtime-generated bot state is now rooted under `BOT_DATA_DIR`.
- Default runtime root is `.runtime/` at repo root.
- State files resolve to `.runtime/state/` by default (for example: `.runtime/state/config.json`, `.runtime/state/paper_state.json`).
- Legacy override `REVBOT_STATE_DIR` is still supported and has priority when set.

## Backward compatibility
- If a file is missing in the new runtime location but exists in the legacy state path (`crypto_bot/state` or `REVBOT_STATE_DIR`), RevBot reads the legacy file as a fallback.
- For key mutable files (`config.json`, `paper_state.json`, `trades.json`), RevBot seeds/copies from legacy location into the new runtime location on first use.

## Operator actions
1. Optional (recommended): set `BOT_DATA_DIR` explicitly for deployments.
2. Keep existing `REVBOT_STATE_DIR` only if you intentionally want legacy behavior.
3. Verify runtime writes now appear under `.runtime/state/` (or your configured `BOT_DATA_DIR`).

## Notes
- Existing filenames are unchanged; only the base directory moved.
- `.gitignore` now ignores `.runtime/`, `var/`, and legacy runtime state directories to avoid committing mutable artifacts.
