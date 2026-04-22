param(
    [string]$StateDir = ".runtime/state",
    [switch]$Apply
)

$ErrorActionPreference = "Stop"
$repoRoot = Resolve-Path (Join-Path $PSScriptRoot "..")
Push-Location $repoRoot
try {
    $normalizedStateDir = ($StateDir -replace "\\", "/").Trim()
    if ([string]::IsNullOrWhiteSpace($normalizedStateDir)) {
        throw "StateDir cannot be empty."
    }
    if ($normalizedStateDir.StartsWith("./")) {
        $normalizedStateDir = $normalizedStateDir.Substring(2)
    }
    if ($normalizedStateDir.StartsWith("/")) {
        throw "StateDir must be a repository-relative path."
    }
    if ($normalizedStateDir -match "^[A-Za-z]:") {
        throw "StateDir must be a repository-relative path."
    }

    $patterns = @("$normalizedStateDir/*", "$normalizedStateDir/**/*")
    $trackedStateFiles = (& git ls-files -- $patterns) | Where-Object { $_ }

    if (-not $trackedStateFiles) {
        Write-Host "No tracked runtime state files found under $normalizedStateDir."
        return
    }

    Write-Host "Tracked runtime state files under ${normalizedStateDir}:"
    $trackedStateFiles | ForEach-Object { Write-Host " - $_" }

    if (-not $Apply) {
        Write-Host ""
        Write-Host "Dry run only. Re-run with -Apply to untrack while keeping files on disk."
        Write-Host "Example: .\\scripts\\untrack_runtime_state.ps1 -Apply"
        return
    }

    git rm --cached -r --ignore-unmatch -- $normalizedStateDir | Out-Null

    Write-Host "Runtime state files under $normalizedStateDir were removed from git index (kept locally)."
    Write-Host "Next: commit .gitignore + index changes."
}
finally {
    Pop-Location
}
