param(
    [switch]$Watch,
    [int]$RestartDelaySeconds = 3,
    [string]$NpmCommand = "dev"
)

$ErrorActionPreference = "Stop"

$repoRoot = Resolve-Path (Join-Path $PSScriptRoot "..")
$uiDir = Join-Path $repoRoot "web-ui"
if (-not (Test-Path $uiDir)) {
    throw "UI directory not found: $uiDir"
}

Push-Location $uiDir
try {
    do {
        npm run $NpmCommand
        $exitCode = $LASTEXITCODE

        if (-not $Watch) {
            exit $exitCode
        }

        Write-Host "UI exited with code $exitCode. Restarting in $RestartDelaySeconds seconds..."
        Start-Sleep -Seconds $RestartDelaySeconds
    } while ($true)
}
finally {
    Pop-Location
}
