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

## 2) Restore state

```powershell
.\scripts\restore_state.ps1
```

Restores the latest backup by default.

To restore a specific backup:

```powershell
.\scripts\restore_state.ps1 -BackupName 20260313-055226
```

## 3) Generate strategy hash baseline

```powershell
.\scripts\generate_strategy_baseline.ps1
```

Writes `crypto_bot/strategy/strategy_hash_baseline.json`.

## 4) Check for strategy drift

```powershell
.\scripts\check_strategy_hashes.ps1
```

Fails if any of these files changed:
- `strategy_engine.py`
- `regime.py`
- `scoring.py`

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

## Control server health/readiness

- `GET /health` -> process is alive
- `GET /ready` -> startup checks for state dir/config/json health

Environment flags:
- `REVBOT_CONTROL_HOST` (default `127.0.0.1`)
- `REVBOT_CONTROL_PORT` (default `8001`)
- `REVBOT_CONTROL_STRICT_STARTUP=1` -> fail startup if readiness checks fail
