param(
    [switch]$Watch,
    [int]$RestartDelaySeconds = 3,
    [string]$PythonPath = "",
    [string]$InitialRestartCause = "manual",
    [ValidateSet("paper", "deploy")][string]$RuntimeMode = "paper"
)

$ErrorActionPreference = "Stop"

$repoRoot = Resolve-Path (Join-Path $PSScriptRoot "..")
$runtimeDataDir = if (-not [string]::IsNullOrWhiteSpace($env:BOT_DATA_DIR)) {
    $env:BOT_DATA_DIR
}
else {
    Join-Path $repoRoot ".runtime"
}
$stateDir = Join-Path $runtimeDataDir "state"
$runtimeEventsPath = Join-Path $stateDir "runtime_events.jsonl"
if (-not $PythonPath) {
    $PythonPath = Join-Path $repoRoot ".venv\Scripts\python.exe"
}
if (-not (Test-Path $PythonPath)) {
    throw "Python not found: $PythonPath"
}

$target = Join-Path $repoRoot "crypto_bot\control\run_control.py"
if (-not (Test-Path $target)) {
    throw "Control entrypoint not found: $target"
}

function Write-RuntimeEvent {
    param(
        [Parameter(Mandatory = $true)][string]$EventType,
        [hashtable]$Fields = @{}
    )

    try {
        New-Item -ItemType Directory -Path $stateDir -Force | Out-Null
        $now = [DateTimeOffset]::UtcNow
        $payload = [ordered]@{
            event_type = $EventType
            time_utc = $now.ToString("o")
            day_utc = $now.ToString("yyyy-MM-dd")
            service = "control_launcher"
            pid = $PID
        }
        foreach ($key in $Fields.Keys) {
            $payload[$key] = $Fields[$key]
        }
        ($payload | ConvertTo-Json -Compress) + "`n" | Out-File -FilePath $runtimeEventsPath -Encoding utf8 -Append
    }
    catch {
        # Runtime event logging must never block launcher behavior.
    }
}

$restartCause = if ([string]::IsNullOrWhiteSpace($InitialRestartCause)) { "manual" } else { $InitialRestartCause.Trim() }
$attempt = 0

Push-Location $repoRoot
try {
    if ($RuntimeMode -eq "deploy") {
        $env:REVBOT_DEPLOYMENT_MODE = "1"
    }
    else {
        $env:REVBOT_DEPLOYMENT_MODE = "0"
    }
    $env:REVBOT_ENABLE_LEGACY_STATE_FALLBACK = "0"

    # Ensure crypto_bot is importable when control entrypoint is launched from
    # crypto_bot/control (run_control.py imports top-level modules like `api`).
    $cryptoBotRoot = Join-Path $repoRoot "crypto_bot"
    $existingPythonPath = [string]$env:PYTHONPATH
    $pythonPathEntries = @($cryptoBotRoot)
    if (-not [string]::IsNullOrWhiteSpace($existingPythonPath)) {
        $pythonPathEntries += ($existingPythonPath -split ";")
    }
    $env:PYTHONPATH = (($pythonPathEntries | ForEach-Object { $_.Trim() } | Where-Object { $_ } | Select-Object -Unique) -join ";")
    $env:pythonpath = $env:PYTHONPATH

    # Ensure control API runtime calls do not inherit broken local proxy settings.
    foreach ($proxyVar in @("HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY", "http_proxy", "https_proxy", "all_proxy")) {
        if (Test-Path "Env:$proxyVar") {
            Remove-Item "Env:$proxyVar" -ErrorAction SilentlyContinue
        }
    }
    $existingNoProxy = [string]$env:NO_PROXY
    $noProxyEntries = @("localhost", "127.0.0.1", "::1", "revx.revolut.com")
    if (-not [string]::IsNullOrWhiteSpace($existingNoProxy)) {
        $noProxyEntries += ($existingNoProxy -split ",")
    }
    $env:NO_PROXY = (($noProxyEntries | ForEach-Object { $_.Trim() } | Where-Object { $_ } | Select-Object -Unique) -join ",")
    $env:no_proxy = $env:NO_PROXY

    do {
        $attempt += 1
        $env:REVBOT_RESTART_CAUSE = $restartCause
        Write-RuntimeEvent -EventType "launcher_start" -Fields @{
            service = "control"
            watch_mode = [bool]$Watch
            restart_cause = $restartCause
            attempt = $attempt
            runtime_mode = $RuntimeMode
        }

        & $PythonPath $target
        $exitCode = $LASTEXITCODE

        if (-not $Watch) {
            Write-RuntimeEvent -EventType "launcher_exit" -Fields @{
                service = "control"
                watch_mode = $false
                exit_code = $exitCode
            }
            exit $exitCode
        }

        $restartCause = if ($exitCode -eq 0) { "watchdog" } else { "crash_recovery" }
        Write-RuntimeEvent -EventType "launcher_restart" -Fields @{
            service = "control"
            watch_mode = $true
            exit_code = $exitCode
            next_restart_cause = $restartCause
            restart_delay_seconds = $RestartDelaySeconds
            attempt = $attempt
        }

        Write-Host "Control server exited with code $exitCode. Restarting in $RestartDelaySeconds seconds..."
        Start-Sleep -Seconds $RestartDelaySeconds
    } while ($true)
}
finally {
    Pop-Location
}
