param(
    [string]$StateDir = "crypto_bot/state",
    [switch]$Apply
)

$ErrorActionPreference = "Stop"
$repoRoot = Resolve-Path (Join-Path $PSScriptRoot "..")
Push-Location $repoRoot
try {
    $targets = @(
        "pytest_base_env",
        "tmpbz5d4cs7",
        "pytest_runtime"
    ) | ForEach-Object { Join-Path $StateDir $_ }

    Write-Host "Locked/temporary legacy-state targets:"
    foreach ($target in $targets) {
        Write-Host " - $target"
    }

    if (-not $Apply) {
        Write-Host ""
        Write-Host "Dry run only. Re-run with -Apply to take ownership + remove those directories."
        Write-Host "Example: .\\scripts\\cleanup_locked_legacy_state_dirs.ps1 -Apply"
        return
    }

    foreach ($target in $targets) {
        if (-not (Test-Path $target)) {
            continue
        }

        Write-Host "Processing $target"
        & takeown /F $target /R /D Y | Out-Null
        & icacls $target /grant "$env:USERNAME:(OI)(CI)F" /T | Out-Null
        Remove-Item -LiteralPath $target -Recurse -Force -ErrorAction SilentlyContinue
    }

    Write-Host "Legacy locked/temp directories cleanup complete."
}
finally {
    Pop-Location
}
