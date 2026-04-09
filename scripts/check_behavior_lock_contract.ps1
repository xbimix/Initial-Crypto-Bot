param(
    [string]$BaselinePath = "",
    [string]$RepoRootPath = ""
)

$ErrorActionPreference = "Stop"

$repoRoot = if ($RepoRootPath) { (Resolve-Path $RepoRootPath).Path } else { (Resolve-Path (Join-Path $PSScriptRoot "..")).Path }
if (-not $BaselinePath) {
    $BaselinePath = Join-Path $repoRoot "crypto_bot\strategy\strategy_hash_baseline.json"
}

if (-not (Test-Path $BaselinePath)) {
    Write-Error "Behavior lock baseline not found: $BaselinePath"
    exit 2
}

$baseline = Get-Content -Path $BaselinePath -Raw | ConvertFrom-Json
if (-not $baseline.files) {
    Write-Error "Invalid behavior lock baseline: missing files map"
    exit 2
}

$required = @(
    "crypto_bot/main.py",
    "crypto_bot/strategy/regime_router.py",
    "crypto_bot/strategy/strategy_engine.py"
)

$missing = @()
foreach ($item in $required) {
    if (-not $baseline.files.PSObject.Properties.Name.Contains($item)) {
        $missing += $item
    }
}

if ($missing.Count -gt 0) {
    Write-Error ("Behavior lock baseline is missing required tracked files: " + ($missing -join ", "))
    exit 1
}

Write-Host "Behavior lock contract check passed."
