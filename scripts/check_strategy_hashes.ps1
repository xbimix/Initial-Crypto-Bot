param(
    [string]$StrategyDir = "",
    [string]$BaselinePath = "",
    [string]$RepoRootPath = ""
)

$ErrorActionPreference = "Stop"

$repoRoot = if ($RepoRootPath) { (Resolve-Path $RepoRootPath).Path } else { (Resolve-Path (Join-Path $PSScriptRoot "..")).Path }
$strategyRoot = if ($StrategyDir) { (Resolve-Path $StrategyDir).Path } else { Join-Path $repoRoot "crypto_bot\strategy" }
if (-not $BaselinePath) {
    $BaselinePath = Join-Path $strategyRoot "strategy_hash_baseline.json"
}

if (-not (Test-Path $BaselinePath)) {
    Write-Error "Baseline file not found: $BaselinePath"
    exit 2
}

$baseline = Get-Content -Path $BaselinePath -Raw | ConvertFrom-Json
if (-not $baseline.files) {
    Write-Error "Invalid baseline format: missing 'files'"
    exit 2
}

$failed = $false
foreach ($prop in $baseline.files.PSObject.Properties) {
    $name = [string]$prop.Name
    $expected = [string]$prop.Value
    if ([System.IO.Path]::IsPathRooted($name)) {
        $path = $name
    }
    else {
        $normalized = $name -replace "/", "\"
        if ($normalized -like "crypto_bot\*") {
            $path = Join-Path $repoRoot $normalized
        }
        else {
            $path = Join-Path $strategyRoot $normalized
        }
    }

    if (-not (Test-Path $path)) {
        Write-Host "MISSING: $name"
        $failed = $true
        continue
    }

    $actual = (Get-FileHash -Path $path -Algorithm SHA256).Hash
    if ($actual -ne $expected) {
        Write-Host "CHANGED: $name"
        Write-Host "  expected: $expected"
        Write-Host "  actual:   $actual"
        $failed = $true
    }
}

if ($failed) {
    Write-Error "Behavior-sensitive hash drift detected."
    exit 1
}

Write-Host "Behavior-sensitive hash check passed."
