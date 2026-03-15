param(
    [switch]$Watch,
    [int]$RestartDelaySeconds = 3,
    [string]$PythonPath = "",
    [string]$InitialRestartCause = "manual"
)

$ErrorActionPreference = "Stop"

$repoRoot = Resolve-Path (Join-Path $PSScriptRoot "..")
$stateDir = Join-Path $repoRoot "crypto_bot\state"
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
    do {
        $attempt += 1
        $env:REVBOT_RESTART_CAUSE = $restartCause
        Write-RuntimeEvent -EventType "launcher_start" -Fields @{
            service = "control"
            watch_mode = [bool]$Watch
            restart_cause = $restartCause
            attempt = $attempt
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
