param(
    [string]$StateDir = ".runtime/state",
    [switch]$Apply
)

$ErrorActionPreference = "Stop"
$repoRoot = Resolve-Path (Join-Path $PSScriptRoot "..")
Push-Location $repoRoot
try {
    $stateRoot = [System.IO.Path]::GetFullPath((Join-Path $repoRoot $StateDir))
    $repoRootPath = [System.IO.Path]::GetFullPath([string]$repoRoot)
    if (-not $stateRoot.StartsWith($repoRootPath, [System.StringComparison]::OrdinalIgnoreCase)) {
        throw "StateDir must resolve inside repository root: $StateDir"
    }

    $targets = @(
        "pytest_base_env",
        "tmpbz5d4cs7",
        "pytest_runtime"
    ) | ForEach-Object { Join-Path $stateRoot $_ }

    Write-Host "Locked/temporary state targets:"
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

    Write-Host "Locked/temp directories cleanup complete."
}
finally {
    Pop-Location
}
