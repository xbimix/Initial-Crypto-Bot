param(
    [string]$StrategyDir = "",
    [string]$BaselinePath = ""
)

$ErrorActionPreference = "Stop"

$repoRoot = Resolve-Path (Join-Path $PSScriptRoot "..")
if (-not $StrategyDir) {
    $StrategyDir = Join-Path $repoRoot "crypto_bot\strategy"
}
if (-not $BaselinePath) {
    $BaselinePath = Join-Path $StrategyDir "strategy_hash_baseline.json"
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
    $name = $prop.Name
    $expected = [string]$prop.Value
    $path = Join-Path $StrategyDir $name

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
    Write-Error "Strategy drift detected."
    exit 1
}

Write-Host "Strategy hash check passed."
