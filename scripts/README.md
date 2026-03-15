# Local Hardening Scripts

These scripts are safe for local paper-mode operations and do not change strategy logic.

## Quick Operator Flow

Use the one-page checklist first:

`.\scripts\OPERATOR_CHECKLIST.md`

## 1) Backup state

```powershell
.\scripts\backup_state.ps1
```

Creates a timestamped backup folder under `crypto_bot/state/backups/`.

## Control/Auth environment (required for mutating actions)

Set an auth token before using mutating control endpoints (`/control`, `/kill`, `/risk`, `/symbols`, `/manual-sell`, `/close-all`, etc):

```powershell
$env:REVBOT_CONTROL_AUTH_TOKEN = "change-this-local-token"
```

For the web UI controls, set the client-visible token too:

```powershell
$env:NEXT_PUBLIC_REVBOT_CONTROL_TOKEN = "change-this-local-token"
```

Optional controls:
- `REVBOT_ALLOW_NON_LOCAL_REQUESTS=1` to allow non-loopback mutating requests (default: local-only).
- `REVBOT_MUTATING_PAYLOAD_MAX_BYTES` (default: `65536`).
- `REVBOT_RATE_LIMIT_WINDOW_SECONDS` / `REVBOT_RATE_LIMIT_MAX_REQUESTS` for control server rate limit.
- `REVBOT_UI_RATE_LIMIT_WINDOW_SECONDS` / `REVBOT_UI_RATE_LIMIT_MAX_REQUESTS` for Next API route limit.

## 2) Restore state

```powershell
.\scripts\restore_state.ps1
```

Restores the latest backup by default.

To restore a specific backup:

```powershell
.\scripts\restore_state.ps1 -BackupName 20260313-055226
```

## 3) Generate behavior-sensitive hash baseline

```powershell
.\scripts\generate_strategy_baseline.ps1
```

Writes `crypto_bot/strategy/strategy_hash_baseline.json` with behavior-sensitive module hashes.

## 4) Check for behavior-sensitive drift

```powershell
.\scripts\check_strategy_hashes.ps1
```

Fails if any baseline-tracked behavior-sensitive file changed.
Default baseline scope includes:
- `crypto_bot/strategy/strategy_engine.py`
- `crypto_bot/strategy/regime.py`
- `crypto_bot/strategy/scoring.py`
- `crypto_bot/trading/executor.py`
- `crypto_bot/risk/risk_manager.py`
- `crypto_bot/main.py`
- `crypto_bot/paper/paper_broker.py` (unless excluded during baseline generation)

Behavior lock and baseline policy docs:

- `.\scripts\BEHAVIOR_LOCK.md`
- `.\scripts\BASELINE_POLICY.md`

Run strategy replay regression (from real log-derived fixture):

```powershell
.\scripts\run_strategy_replay.ps1
```

Optional rebuild of replay fixture from logs:

```powershell
python .\scripts\build_strategy_replay_fixture.py
```

## 5) Local setup

```powershell
.\scripts\setup_local.ps1
```

Optional skip web install:

```powershell
.\scripts\setup_local.ps1 -SkipWebInstall
```

Install dev/test dependencies:

```powershell
.\scripts\setup_local.ps1 -InstallDev -SkipWebInstall
```

## 6) Local checks

```powershell
.\scripts\check_local.ps1
```

Skip web build:

```powershell
.\scripts\check_local.ps1 -SkipWebBuild
```

Runs:
- strategy hash check
- Python compile check
- `pytest` test suite
- web advisory tests (`npm run test:wave-zones`)
- `web-ui` build

## Config validation mode

`config_loader.py` now validates/migrates config in memory by default.

Environment flags:
- `REVBOT_CONFIG_STRICT=1` -> fail fast on validation warnings
- `REVBOT_CONFIG_AUTOSAVE_NORMALIZED=1` -> write normalized config back to file
- `REVBOT_MAIN_STRICT_STARTUP=1` -> fail bot startup if startup diagnostics fail

## 7) Start scripts (with optional watchdog mode)

Start bot:

```powershell
.\scripts\start_bot.ps1
```

Start control server:

```powershell
.\scripts\start_control.ps1
```

Start UI:

```powershell
.\scripts\start_ui.ps1
```

Watchdog restart mode:

```powershell
.\scripts\start_bot.ps1 -Watch
.\scripts\start_control.ps1 -Watch
.\scripts\start_ui.ps1 -Watch
```

## 8) Health, recovery, and cleanup

Health/readiness probe:

```powershell
.\scripts\health_check.ps1 -IncludeStatus
```

Recovery flow (restore + checks + optional health probe):

```powershell
.\scripts\recover_local.ps1
```

Cleanup pytest/runtime temp artifacts:

```powershell
.\scripts\cleanup_artifacts.ps1
```

Detailed operational guide:

`.\scripts\RUNBOOK_LOCAL.md`

Pre-UI redesign references:

- `.\scripts\UI_PAYLOAD_CONTRACTS.md`
- `.\scripts\UI_VOCABULARY_MAP.md`
- `.\scripts\UI_SECTION_PRIORITY.md`

## 9) Profile measured bottlenecks

Run local bottleneck profiling (state I/O + log growth + micro-benchmarks):

```powershell
.\scripts\profile_local_bottlenecks.ps1
```

Skip Python micro-benchmarks:

```powershell
.\scripts\profile_local_bottlenecks.ps1 -SkipPythonBench
```

Sample a longer log-growth window:

```powershell
.\scripts\profile_local_bottlenecks.ps1 -SampleSeconds 30
```

Optional state I/O telemetry during runtime (disabled by default):
- `REVBOT_STATE_IO_METRICS=1`
- `REVBOT_STATE_IO_METRICS_INTERVAL_SECONDS=60`

## 10) Generate daily paper summary

Create a daily report with realized/unrealized split, trade reasons, and run-quality counts:

```powershell
python .\scripts\generate_daily_summary.py
```

Generate for a specific UTC day:

```powershell
python .\scripts\generate_daily_summary.py --day 2026-03-14
```

Write to a custom output file:

```powershell
python .\scripts\generate_daily_summary.py --day 2026-03-14 --output .\crypto_bot\state\reports\daily_summary_2026-03-14.json
```

## 11) Generate weekly validation summary

Create a weekly operational summary from daily artifacts:

```powershell
python .\scripts\generate_weekly_summary.py --days 7
```

Set an explicit end day:

```powershell
python .\scripts\generate_weekly_summary.py --end-day 2026-03-14 --days 7
```

## Control server health/readiness

- `GET /health` -> process is alive
- `GET /ready` -> startup checks for state dir/config/json health

Environment flags:
- `REVBOT_CONTROL_HOST` (default `127.0.0.1`)
- `REVBOT_CONTROL_PORT` (default `8001`)
- `REVBOT_CONTROL_STRICT_STARTUP=1` -> fail startup if readiness checks fail
