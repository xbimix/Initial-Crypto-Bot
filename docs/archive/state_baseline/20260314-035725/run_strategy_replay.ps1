param(
    [string]$FixturePath = "",
    [string]$OutputPath = ""
)

$ErrorActionPreference = "Stop"

$repoRoot = Resolve-Path (Join-Path $PSScriptRoot "..")
$venvPython = Join-Path $repoRoot ".venv\Scripts\python.exe"

if (-not $FixturePath) {
    $FixturePath = Join-Path $repoRoot "crypto_bot\tests\fixtures\strategy_replay_cases.json"
}

if (-not $OutputPath) {
    $reportsDir = Join-Path $repoRoot "crypto_bot\state\reports"
    New-Item -ItemType Directory -Path $reportsDir -Force | Out-Null
    $timestamp = Get-Date -Format "yyyyMMdd-HHmmss"
    $OutputPath = Join-Path $reportsDir "strategy_replay_$timestamp.json"
}

& $venvPython (Join-Path $repoRoot "scripts\replay_strategy_regression.py") `
    --fixture $FixturePath `
    --output $OutputPath

if ($LASTEXITCODE -ne 0) {
    throw "Strategy replay regression failed (exit code $LASTEXITCODE)"
}

Write-Host "Strategy replay regression passed: $OutputPath"
