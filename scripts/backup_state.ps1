param(
    [string]$StateDir = "",
    [string]$BackupRoot = ""
)

$ErrorActionPreference = "Stop"

$repoRoot = Resolve-Path (Join-Path $PSScriptRoot "..")
if (-not $StateDir) {
    $StateDir = Join-Path $repoRoot "crypto_bot\state"
}
if (-not $BackupRoot) {
    $BackupRoot = Join-Path $StateDir "backups"
}

$statePath = Resolve-Path $StateDir
if (-not $statePath) {
    throw "State directory not found: $StateDir"
}

New-Item -ItemType Directory -Path $BackupRoot -Force | Out-Null

$timestamp = Get-Date -Format "yyyyMMdd-HHmmss"
$backupDir = Join-Path $BackupRoot $timestamp
New-Item -ItemType Directory -Path $backupDir -Force | Out-Null

$files = @(
    "config.json",
    "paper_state.json",
    "strategy_state.json",
    "trades.json",
    "state.json"
)

$copied = @()
foreach ($name in $files) {
    $source = Join-Path $statePath $name
    if (Test-Path $source) {
        Copy-Item -Path $source -Destination (Join-Path $backupDir $name) -Force
        $hash = (Get-FileHash -Path (Join-Path $backupDir $name) -Algorithm SHA256).Hash
        $copied += [ordered]@{
            file = $name
            sha256 = $hash
        }
    }
}

if ($copied.Count -eq 0) {
    throw "No state files found to backup in $statePath"
}

$manifest = [ordered]@{
    created_at_utc = [DateTime]::UtcNow.ToString("o")
    state_dir = "$statePath"
    files = $copied
}

$manifest | ConvertTo-Json -Depth 8 | Set-Content -Path (Join-Path $backupDir "manifest.json") -Encoding UTF8
Write-Host "Backup created: $backupDir"
