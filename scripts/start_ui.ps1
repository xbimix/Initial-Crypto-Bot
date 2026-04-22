param(
    [switch]$Watch,
    [int]$RestartDelaySeconds = 3,
    [string]$NpmCommand = "dev",
    [string]$InitialRestartCause = "manual"
)

$ErrorActionPreference = "Stop"

$repoRoot = Resolve-Path (Join-Path $PSScriptRoot "..")
$uiDir = Join-Path $repoRoot "web-ui"
$runtimeDataDir = if (-not [string]::IsNullOrWhiteSpace($env:BOT_DATA_DIR)) {
    $env:BOT_DATA_DIR
}
else {
    Join-Path $repoRoot ".runtime"
}
$stateDir = Join-Path $runtimeDataDir "state"
$runtimeEventsPath = Join-Path $stateDir "runtime_events.jsonl"
if (-not (Test-Path $uiDir)) {
    throw "UI directory not found: $uiDir"
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
            service = "ui_launcher"
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

Push-Location $uiDir
try {
    do {
        $attempt += 1
        Write-RuntimeEvent -EventType "launcher_start" -Fields @{
            service = "ui"
            watch_mode = [bool]$Watch
            restart_cause = $restartCause
            attempt = $attempt
            npm_command = $NpmCommand
        }

        npm run $NpmCommand
        $exitCode = $LASTEXITCODE

        if (-not $Watch) {
            Write-RuntimeEvent -EventType "launcher_exit" -Fields @{
                service = "ui"
                watch_mode = $false
                exit_code = $exitCode
            }
            exit $exitCode
        }

        $restartCause = if ($exitCode -eq 0) { "watchdog" } else { "crash_recovery" }
        Write-RuntimeEvent -EventType "launcher_restart" -Fields @{
            service = "ui"
            watch_mode = $true
            exit_code = $exitCode
            next_restart_cause = $restartCause
            restart_delay_seconds = $RestartDelaySeconds
            attempt = $attempt
        }

        Write-Host "UI exited with code $exitCode. Restarting in $RestartDelaySeconds seconds..."
        Start-Sleep -Seconds $RestartDelaySeconds
    } while ($true)
}
finally {
    Pop-Location
}
