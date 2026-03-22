param(
    [switch]$IncludeWebCache
)

$ErrorActionPreference = "Stop"

$repoRoot = Resolve-Path (Join-Path $PSScriptRoot "..")

$patterns = @(
    ".pytest_cache",
    "pytest-cache-files-*",
    "scripts\_pytest_tmp*",
    "scripts\pytest-cache-files-*",
    "crypto_bot\pytest-cache-files-*",
    "crypto_bot\work_testdirs\case_*",
    "crypto_bot\state\.pytest_cache*",
    "crypto_bot\state\pytest_tmp*",
    "crypto_bot\state\pytest-cache-files-*",
    "crypto_bot\state\pytest_base_env",
    "crypto_bot\state\pytest_tmp_codex",
    "crypto_bot\state\replay_tmp\run_*",
    "crypto_bot\tests\.pytest_cache*",
    "crypto_bot\tests\_pytest_tmp*",
    "crypto_bot\tests\pytest-cache-files-*"
)

if ($IncludeWebCache) {
    $patterns += "web-ui\.next"
}

$removed = @()
$failed = @()

Push-Location $repoRoot
try {
    foreach ($pattern in $patterns) {
        $items = Get-ChildItem -Path $pattern -Force -ErrorAction SilentlyContinue
        foreach ($item in $items) {
            try {
                Remove-Item -Path $item.FullName -Recurse -Force -ErrorAction Stop
                if (-not (Test-Path $item.FullName)) {
                    $removed += $item.FullName
                }
                else {
                    $failed += $item.FullName
                }
            }
            catch {
                $failed += $item.FullName
            }
        }
    }
}
finally {
    Pop-Location
}

Write-Host "Cleanup complete."
Write-Host "Removed: $($removed.Count)"
if ($removed.Count -gt 0) {
    $removed | ForEach-Object { Write-Host "  OK  $_" }
}
Write-Host "Failed: $($failed.Count)"
if ($failed.Count -gt 0) {
    $failed | ForEach-Object { Write-Host "  ERR $_" }
}
