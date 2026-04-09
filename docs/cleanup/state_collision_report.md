# State Collision Report

Date: 2026-04-06

## Collision Check
Compared file names between:
- `.runtime/state/`
- `crypto_bot/state/`

## Result
Multiple duplicate filenames exist across runtime and legacy locations, including:
- `config.json`
- `strategy_state.json`
- `paper_state.json`
- `trades.json`
- `market_data.db`
- `decision_audit.jsonl`
- `runtime_events.jsonl`
- `revolut_account_snapshot.json`
- `revolut_universe_snapshot.json`

Observed file sizes differ across all sampled overlaps, confirming divergence risk.

## Impact
Any caller using legacy fallback may observe stale or conflicting state depending on path resolution.

## Action
Continue runtime-state unification and restrict legacy usage to explicit migration fallback reads only.
