param(
    [switch]$Watch,
    [int]$RestartDelaySeconds = 3,
    [string]$PythonPath = ""
)

$ErrorActionPreference = "Stop"

$repoRoot = Resolve-Path (Join-Path $PSScriptRoot "..")
if (-not $PythonPath) {
    $PythonPath = Join-Path $repoRoot ".venv\Scripts\python.exe"
}
if (-not (Test-Path $PythonPath)) {
    throw "Python not found: $PythonPath"
}

$target = Join-Path $repoRoot "crypto_bot\main.py"
if (-not (Test-Path $target)) {
    throw "Bot entrypoint not found: $target"
}

Push-Location $repoRoot
try {
    do {
        & $PythonPath $target
        $exitCode = $LASTEXITCODE

        if (-not $Watch) {
            exit $exitCode
        }

        Write-Host "Bot exited with code $exitCode. Restarting in $RestartDelaySeconds seconds..."
        Start-Sleep -Seconds $RestartDelaySeconds
    } while ($true)
}
finally {
    Pop-Location
}
