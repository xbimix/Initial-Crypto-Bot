param(
    [switch]$SkipWebBuild
)

$ErrorActionPreference = "Stop"

$repoRoot = Resolve-Path (Join-Path $PSScriptRoot "..")
$venvPython = Join-Path $repoRoot ".venv\Scripts\python.exe"

function Invoke-Checked {
    param(
        [Parameter(Mandatory = $true)][string]$Command,
        [string[]]$Arguments = @()
    )

    & $Command @Arguments
    if ($LASTEXITCODE -ne 0) {
        throw "Command failed ($LASTEXITCODE): $Command $($Arguments -join ' ')"
    }
}

Push-Location $repoRoot
try {
    & "$PSScriptRoot\check_strategy_hashes.ps1"
    if (-not $?) {
        throw "Strategy hash check failed"
    }

    Invoke-Checked -Command $venvPython -Arguments @("-m", "compileall", ".\crypto_bot")
    $pytestBaseTemp = ".\crypto_bot\state\pytest_tmp_$PID"
    $pytestCacheDir = ".\crypto_bot\state\.pytest_cache_$PID"

    try {
        Invoke-Checked -Command $venvPython -Arguments @(
            "-m",
            "pytest",
            ".\crypto_bot\tests",
            "-q",
            "--basetemp=$pytestBaseTemp",
            "-o",
            "cache_dir=$pytestCacheDir"
        )
    }
    finally {
        Remove-Item -Recurse -Force $pytestBaseTemp -ErrorAction SilentlyContinue
        Remove-Item -Recurse -Force $pytestCacheDir -ErrorAction SilentlyContinue
    }

    if (-not $SkipWebBuild) {
        Push-Location .\web-ui
        try {
            Invoke-Checked -Command "npm" -Arguments @("run", "build")
        }
        finally {
            Pop-Location
        }
    }
}
finally {
    Pop-Location
}

Write-Host "Local checks passed."
