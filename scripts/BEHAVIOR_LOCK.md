# RevBot Behavior Lock (Phase A)

This document freezes current paper-trading behavior and defines guardrails for refactors.

## Scope

Behavior means strategy decisions, risk gating, and trade execution sequencing for paper mode.

Behavior-sensitive modules (directly affect trading outcomes):

- `crypto_bot/strategy/strategy_engine.py`
- `crypto_bot/strategy/regime.py`
- `crypto_bot/strategy/scoring.py`
- `crypto_bot/trading/executor.py`
- `crypto_bot/risk/risk_manager.py`
- `crypto_bot/main.py`
- `crypto_bot/paper/paper_broker.py`
- `crypto_bot/data/market_data.py`

## Lock Rules

1. Do not change behavior-sensitive modules without both:
   - strategy hash check (`scripts/check_strategy_hashes.ps1`)
   - replay/regression validation (`scripts/run_strategy_replay.ps1` and pytest strategy tests)
2. Any change that can alter order timing, state transitions, or risk gating is high risk.
3. If an improvement conflicts with preserving behavior, preserve behavior and document the trade-off.
4. Prefer wrappers/validators/observability around behavior-sensitive code over direct rewrites.
5. Keep JSON paper state compatibility (`paper_state.json`, `strategy_state.json`, `trades.json`).

## Required Gates Before Merge

- `scripts/check_strategy_hashes.ps1`
  - Hash baseline includes `strategy_engine.py`, `regime.py`, `scoring.py`, `executor.py`, `risk_manager.py`, `main.py`, and `paper_broker.py` by default.
- `scripts/run_strategy_replay.ps1`
- `python -m pytest crypto_bot/tests/test_strategy_regression.py -q`
- `python -m pytest crypto_bot/tests/test_strategy_replay_fixture.py -q`
- `python -m pytest crypto_bot/tests/test_risk_manager.py -q`

## Baseline Inputs

- Strategy hash baseline file: `crypto_bot/strategy/strategy_hash_baseline.json`
- Runtime baseline snapshots: `.runtime/state/backups/*`
- Replay fixture from real logs: `crypto_bot/tests/fixtures/strategy_replay_cases.json`
- Replay diff artifacts: `.runtime/state/reports/strategy_replay_*.json`
