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

    & "$PSScriptRoot\run_strategy_replay.ps1"
    if (-not $?) {
        throw "Strategy replay regression failed"
    }

    Invoke-Checked -Command $venvPython -Arguments @(
        "-m",
        "compileall",
        ".\crypto_bot",
        "-x",
        "(state|tests|work_testdirs|pytest-cache-files|_pytest_tmp)"
    )
    Invoke-Checked -Command $venvPython -Arguments @(
        "-m",
        "pytest",
        ".\crypto_bot\tests",
        "-q",
        "-p",
        "no:cacheprovider",
        "-p",
        "no:tmpdir",
        "--ignore-glob=.\crypto_bot\tests\_pytest_tmp_*",
        "--ignore-glob=.\crypto_bot\tests\pytest-cache-files-*",
        "--ignore-glob=.\crypto_bot\state\pytest_*",
        "--ignore-glob=.\crypto_bot\state\pytest-cache-files-*"
    )

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
