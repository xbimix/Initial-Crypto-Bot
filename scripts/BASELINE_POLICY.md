# Baseline Snapshot Policy (Phase A)

This policy defines what is included in strategy drift checks versus runtime continuity artifacts.

## Strategy Drift Baseline

Behavior-sensitive hash drift checks cover:

- `crypto_bot/strategy/strategy_engine.py`
- `crypto_bot/strategy/regime.py`
- `crypto_bot/strategy/scoring.py`
- `crypto_bot/trading/executor.py`
- `crypto_bot/risk/risk_manager.py`
- `crypto_bot/main.py`
- `crypto_bot/paper/paper_broker.py` (included by default; can be excluded when intentionally running `generate_strategy_baseline.ps1 -ExcludePaperBroker`)

Source of truth:
- `crypto_bot/strategy/strategy_hash_baseline.json`

Commands:

```powershell
.\scripts\generate_strategy_baseline.ps1
.\scripts\check_strategy_hashes.ps1
```

## Runtime State Baseline (Continuity Only)

Runtime JSON files are preserved for recovery and replay inputs, but they are not part of strategy hash drift checks:

- `.runtime/state/paper_state.json`
- `.runtime/state/strategy_state.json`
- `.runtime/state/trades.json`
- `.runtime/state/config.json`
- `.runtime/state/state.json`

Snapshot command:

```powershell
.\scripts\backup_state.ps1
```

Snapshots are stored under:

- `.runtime/state/backups/YYYYMMDD-HHMMSS/`

## Replay Baseline

Replay fixtures must come from real runtime artifacts (logs/snapshots) and be stable under current behavior lock.

Primary files:

- Fixture: `crypto_bot/tests/fixtures/strategy_replay_cases.json`
- Diff outputs: `.runtime/state/reports/strategy_replay_*.json`

Commands:

```powershell
.\scripts\run_strategy_replay.ps1
```

Optional fixture rebuild (from logs):

```powershell
python .\scripts\build_strategy_replay_fixture.py
```
