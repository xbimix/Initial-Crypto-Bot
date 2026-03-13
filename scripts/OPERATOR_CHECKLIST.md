# RevBot Operator Checklist (One Page)

Use this for daily local paper-mode operation.

## A) Start of day (2-3 minutes)

1. Open terminal at repo root:

```powershell
cd d:\Python-Codes\RevBot
```

2. Strategy safety + local checks:

```powershell
.\scripts\check_strategy_hashes.ps1
.\scripts\check_local.ps1 -SkipWebBuild
```

3. Create fresh state backup:

```powershell
.\scripts\backup_state.ps1
```

4. Start services in separate terminals:

```powershell
.\scripts\start_control.ps1
.\scripts\start_bot.ps1
.\scripts\start_ui.ps1
```

5. Validate control server health:

```powershell
.\scripts\health_check.ps1 -IncludeStatus
```

Expected: `health` and `ready` show `[OK]`.

## B) During session (monitor loop)

1. Keep UI open and verify:
- bot enabled state
- no repeated API/control errors
- positions/trades updating normally

2. Repeat health check when needed:

```powershell
.\scripts\health_check.ps1 -IncludeStatus
```

3. If something looks off, make immediate backup:

```powershell
.\scripts\backup_state.ps1
```

## C) Emergency actions

1. Emergency stop from UI (`KILL`) or API:

```powershell
Invoke-RestMethod -Uri "http://127.0.0.1:8001/kill" -Method Post
```

2. Confirm disabled/emergency state:

```powershell
Invoke-RestMethod -Uri "http://127.0.0.1:8001/status" -Method Get
```

3. If state looks corrupted/inconsistent:

```powershell
.\scripts\recover_local.ps1
```

Or specific backup:

```powershell
.\scripts\recover_local.ps1 -BackupName <timestamp-folder>
```

## D) End of day

1. Stop bot from UI (`STOP`) or API:

```powershell
Invoke-RestMethod -Uri "http://127.0.0.1:8001/control" -Method Post -ContentType "application/json" -Body '{"action":"STOP"}'
```

2. Final backup:

```powershell
.\scripts\backup_state.ps1
```

3. Optional cleanup of temp artifacts:

```powershell
.\scripts\cleanup_artifacts.ps1
```

## E) Quick troubleshooting

1. Control server not reachable:
- ensure `start_control.ps1` terminal is running
- rerun `.\scripts\health_check.ps1`

2. Bot not trading:
- check `/status` enabled/emergency flags
- verify token BUY/SELL toggles in UI
- check risk constraints and cooldowns in UI

3. Validation/build issues:
- run `.\scripts\check_local.ps1 -SkipWebBuild`
- if needed, run `.\scripts\setup_local.ps1 -InstallDev -SkipWebInstall`
