# Runtime Path Truth

Date: 2026-04-06

## Source Of Truth
Path resolution is implemented in `crypto_bot/utils/state_paths.py`.

## Effective Resolution Rules
1. If `REVBOT_STATE_DIR` is set -> legacy override path is used.
2. Else `BOT_DATA_DIR` if set -> runtime root from env.
3. Else default runtime root -> `<project>/.runtime`.
4. State dir resolves to `<runtime_root>/<state_dir_name>` (typically `.runtime/state`).

## Config Path Reality
- Active runtime config should be read from `.runtime/state/config.json`.
- `crypto_bot/state/config.json` is legacy fallback and may diverge.

## Recommendation
Complete migration by eliminating implicit legacy writes and keeping legacy reads as explicit one-way fallback only.
