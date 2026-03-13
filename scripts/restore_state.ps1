param(
    [string]$StateDir = "",
    [string]$BackupRoot = "",
    [string]$BackupName = ""
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

if (-not (Test-Path $BackupRoot)) {
    throw "Backup root not found: $BackupRoot"
}

if (-not $BackupName) {
    $latest = Get-ChildItem -Path $BackupRoot -Directory | Sort-Object Name -Descending | Select-Object -First 1
    if (-not $latest) {
        throw "No backups found in $BackupRoot"
    }
    $BackupName = $latest.Name
}

$backupDir = Join-Path $BackupRoot $BackupName
if (-not (Test-Path $backupDir)) {
    throw "Backup not found: $backupDir"
}

$files = @(
    "config.json",
    "paper_state.json",
    "strategy_state.json",
    "trades.json",
    "state.json"
)

$restored = @()
foreach ($name in $files) {
    $source = Join-Path $backupDir $name
    if (Test-Path $source) {
        Copy-Item -Path $source -Destination (Join-Path $statePath $name) -Force
        $restored += $name
    }
}

if ($restored.Count -eq 0) {
    throw "Backup exists but no recognized state files were found: $backupDir"
}

Write-Host "Restored backup '$BackupName' to $statePath"
Write-Host "Files: $($restored -join ', ')"
