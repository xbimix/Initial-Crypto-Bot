# RevBot Local Runbook

This runbook is for local paper-mode operation.
It does not require strategy logic changes.

## 1) Preflight

From repo root (`d:\Python-Codes\RevBot`):

```powershell
.\scripts\check_strategy_hashes.ps1
.\scripts\setup_local.ps1 -InstallDev -SkipWebInstall
```

## 2) Start services (3 terminals)

Terminal A:

```powershell
.\scripts\start_control.ps1
```

Terminal B:

```powershell
.\scripts\start_bot.ps1
```

Terminal C:

```powershell
cd .\web-ui
npm run dev
```

Optional watchdog mode:

```powershell
.\scripts\start_control.ps1 -Watch
.\scripts\start_bot.ps1 -Watch
.\scripts\start_ui.ps1 -Watch
```

## 3) Runtime health checks

```powershell
.\scripts\health_check.ps1 -IncludeStatus
```

Expected:
- `/health` ok
- `/ready` ok

## 4) Daily safe checks

```powershell
.\scripts\backup_state.ps1
.\scripts\check_local.ps1 -SkipWebBuild
```

## 5) Emergency recovery

If something looks wrong:

```powershell
.\scripts\recover_local.ps1
```

Restore a specific backup:

```powershell
.\scripts\recover_local.ps1 -BackupName 20260313-055226
```

If control server is intentionally offline:

```powershell
.\scripts\recover_local.ps1 -SkipHealth
```

## 6) Cleanup local artifacts

```powershell
.\scripts\cleanup_artifacts.ps1
```

Also clean web build cache:

```powershell
.\scripts\cleanup_artifacts.ps1 -IncludeWebCache
```

## 7) Strict startup modes (optional)

Bot strict startup:

```powershell
$env:REVBOT_MAIN_STRICT_STARTUP="1"
```

Control strict startup:

```powershell
$env:REVBOT_CONTROL_STRICT_STARTUP="1"
```

Use strict modes only once your state/config files are stable.
