param(
    [string]$StrategyDir = "",
    [string]$OutputPath = ""
)

$ErrorActionPreference = "Stop"

$repoRoot = Resolve-Path (Join-Path $PSScriptRoot "..")
if (-not $StrategyDir) {
    $StrategyDir = Join-Path $repoRoot "crypto_bot\strategy"
}
if (-not $OutputPath) {
    $OutputPath = Join-Path $StrategyDir "strategy_hash_baseline.json"
}

$files = @(
    "strategy_engine.py",
    "regime.py",
    "scoring.py"
)

$hashes = [ordered]@{}
foreach ($name in $files) {
    $path = Join-Path $StrategyDir $name
    if (-not (Test-Path $path)) {
        throw "Missing strategy file: $path"
    }
    $hashes[$name] = (Get-FileHash -Path $path -Algorithm SHA256).Hash
}

$payload = [ordered]@{
    generated_at_utc = [DateTime]::UtcNow.ToString("o")
    files = $hashes
}

$payload | ConvertTo-Json -Depth 6 | Set-Content -Path $OutputPath -Encoding UTF8
Write-Host "Strategy baseline written: $OutputPath"
