param(
    [switch]$Apply
)

$ErrorActionPreference = "Stop"
$repoRoot = Resolve-Path (Join-Path $PSScriptRoot "..")
Push-Location $repoRoot
try {
    $trackedStateFiles = git ls-files "crypto_bot/state/*" "crypto_bot/state/**/*" | Where-Object { $_ }

    if (-not $trackedStateFiles) {
        Write-Host "No tracked runtime state files found."
        return
    }

    Write-Host "Tracked runtime state files:"
    $trackedStateFiles | ForEach-Object { Write-Host " - $_" }

    if (-not $Apply) {
        Write-Host ""
        Write-Host "Dry run only. Re-run with -Apply to untrack while keeping files on disk."
        Write-Host "Example: .\\scripts\\untrack_runtime_state.ps1 -Apply"
        return
    }

    git rm --cached -r --ignore-unmatch crypto_bot/state | Out-Null

    Write-Host "Runtime state files were removed from git index (kept locally)."
    Write-Host "Next: commit .gitignore + index changes."
}
finally {
    Pop-Location
}
