param(
    [string]$StrategyDir = "",
    [string]$OutputPath = "",
    [switch]$ExcludePaperBroker
)

$ErrorActionPreference = "Stop"

$repoRoot = Resolve-Path (Join-Path $PSScriptRoot "..")
$strategyRoot = if ($StrategyDir) { (Resolve-Path $StrategyDir).Path } else { Join-Path $repoRoot "crypto_bot\strategy" }
if (-not $OutputPath) {
    $OutputPath = Join-Path $strategyRoot "strategy_hash_baseline.json"
}

$files = @(
    "crypto_bot/strategy/strategy_engine.py",
    "crypto_bot/strategy/regime.py",
    "crypto_bot/strategy/scoring.py",
    "crypto_bot/trading/executor.py",
    "crypto_bot/risk/risk_manager.py",
    "crypto_bot/main.py"
)
if (-not $ExcludePaperBroker) {
    $files += "crypto_bot/paper/paper_broker.py"
}

$hashes = [ordered]@{}
foreach ($name in $files) {
    $path = Join-Path $repoRoot $name
    if (-not (Test-Path $path)) {
        throw "Missing behavior-sensitive file: $path"
    }
    $hashes[$name] = (Get-FileHash -Path $path -Algorithm SHA256).Hash
}

$payload = [ordered]@{
    generated_at_utc = [DateTime]::UtcNow.ToString("o")
    hash_scope = "behavior_sensitive"
    repo_root = [string]$repoRoot
    files = $hashes
}

$payload | ConvertTo-Json -Depth 6 | Set-Content -Path $OutputPath -Encoding UTF8
Write-Host "Strategy baseline written: $OutputPath"
