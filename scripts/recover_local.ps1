param(
    [string]$BackupName = "",
    [switch]$SkipRestore,
    [switch]$SkipHealth,
    [string]$BaseUrl = "http://127.0.0.1:8001"
)

$ErrorActionPreference = "Stop"

$repoRoot = Resolve-Path (Join-Path $PSScriptRoot "..")
$venvPython = Join-Path $repoRoot ".venv\Scripts\python.exe"

function Run-Script {
    param(
        [Parameter(Mandatory = $true)][string]$Path,
        [string[]]$Args = @()
    )
    & $Path @Args
    if ($LASTEXITCODE -ne 0) {
        throw "Command failed ($LASTEXITCODE): $Path $($Args -join ' ')"
    }
}

Push-Location $repoRoot
try {
    if (-not $SkipRestore) {
        $restoreArgs = @()
        if ($BackupName) {
            $restoreArgs += @("-BackupName", $BackupName)
        }
        Run-Script -Path (Join-Path $PSScriptRoot "restore_state.ps1") -Args $restoreArgs
    }

    Run-Script -Path (Join-Path $PSScriptRoot "check_strategy_hashes.ps1")
    & $venvPython -m compileall .\crypto_bot
    if ($LASTEXITCODE -ne 0) {
        throw "compileall failed"
    }

    if (-not $SkipHealth) {
        Run-Script -Path (Join-Path $PSScriptRoot "health_check.ps1") -Args @("-BaseUrl", $BaseUrl)
    }
}
finally {
    Pop-Location
}

Write-Host "Recovery flow complete."
