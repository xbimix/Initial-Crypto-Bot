param(
    [switch]$SkipWebBuild
)

$ErrorActionPreference = "Stop"

$repoRoot = Resolve-Path (Join-Path $PSScriptRoot "..")
$venvPython = Join-Path $repoRoot ".venv\Scripts\python.exe"
$compileTargets = @(
    ".\crypto_bot\analysis",
    ".\crypto_bot\api",
    ".\crypto_bot\config",
    ".\crypto_bot\control",
    ".\crypto_bot\data",
    ".\crypto_bot\domain",
    ".\crypto_bot\paper",
    ".\crypto_bot\reporting",
    ".\crypto_bot\risk",
    ".\crypto_bot\strategy",
    ".\crypto_bot\trading",
    ".\crypto_bot\ui",
    ".\crypto_bot\utils"
)

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

    $compileArgs = @(
        "-m",
        "compileall",
        "-q"
    ) + $compileTargets
    Invoke-Checked -Command $venvPython -Arguments $compileArgs
    $previousStateDir = $env:REVBOT_STATE_DIR
    $pytestStateDir = Join-Path $repoRoot "crypto_bot\state\pytest_runtime"
    New-Item -ItemType Directory -Path $pytestStateDir -Force | Out-Null
    $defaultStateDir = Join-Path $repoRoot "crypto_bot\state"
    foreach ($name in @("config.json", "paper_state.json", "strategy_state.json", "trades.json")) {
        $targetPath = Join-Path $pytestStateDir $name
        if (Test-Path $targetPath) {
            continue
        }
        $sourcePath = Join-Path $defaultStateDir $name
        if (Test-Path $sourcePath) {
            Copy-Item -Path $sourcePath -Destination $targetPath -Force
            continue
        }
        switch ($name) {
            "config.json" {
                @{ starting_balance = 10000; symbols = @(); token_regimes = @{}; trading_enabled = $true; emergency_stop = $false } |
                    ConvertTo-Json -Depth 10 | Out-File -FilePath $targetPath -Encoding utf8
            }
            "paper_state.json" {
                @{ balance = 10000; positions = @{} } | ConvertTo-Json -Depth 10 | Out-File -FilePath $targetPath -Encoding utf8
            }
            "strategy_state.json" {
                @{} | ConvertTo-Json -Depth 10 | Out-File -FilePath $targetPath -Encoding utf8
            }
            "trades.json" {
                @() | ConvertTo-Json -Depth 10 | Out-File -FilePath $targetPath -Encoding utf8
            }
        }
    }
    $env:REVBOT_STATE_DIR = $pytestStateDir
    try {
        Invoke-Checked -Command $venvPython -Arguments @(
            "-m",
            "pytest",
            ".\crypto_bot\tests",
            "-q",
            "-p",
            "no:cacheprovider",
            "-p",
            "no:tmpdir",
            "-p",
            "no:stepwise",
            "--ignore-glob=.\crypto_bot\tests\_pytest_tmp_*",
            "--ignore-glob=.\crypto_bot\tests\pytest-cache-files-*",
            "--ignore-glob=.\crypto_bot\state\pytest_*",
            "--ignore-glob=.\crypto_bot\state\pytest-cache-files-*"
        )
    }
    finally {
        if ($null -eq $previousStateDir) {
            Remove-Item Env:REVBOT_STATE_DIR -ErrorAction SilentlyContinue
        }
        else {
            $env:REVBOT_STATE_DIR = $previousStateDir
        }
    }

    if (-not $SkipWebBuild) {
        Push-Location .\web-ui
        try {
            Invoke-Checked -Command "npm" -Arguments @("run", "test:wave-zones")
            Invoke-Checked -Command "npm" -Arguments @("run", "lint")
            Invoke-Checked -Command "npx" -Arguments @("tsc", "--noEmit")

            $previousNextValidation = $env:REVBOT_SKIP_NEXT_BUILD_VALIDATION
            $previousNextWorkaround = $env:REVBOT_NEXT_LOCAL_BUILD_WORKAROUND
            $env:REVBOT_SKIP_NEXT_BUILD_VALIDATION = "1"
            $env:REVBOT_NEXT_LOCAL_BUILD_WORKAROUND = "1"
            try {
                Invoke-Checked -Command "npx" -Arguments @(
                    "next",
                    "build",
                    "--experimental-build-mode",
                    "compile"
                )
            }
            finally {
                if ($null -eq $previousNextValidation) {
                    Remove-Item Env:REVBOT_SKIP_NEXT_BUILD_VALIDATION -ErrorAction SilentlyContinue
                }
                else {
                    $env:REVBOT_SKIP_NEXT_BUILD_VALIDATION = $previousNextValidation
                }

                if ($null -eq $previousNextWorkaround) {
                    Remove-Item Env:REVBOT_NEXT_LOCAL_BUILD_WORKAROUND -ErrorAction SilentlyContinue
                }
                else {
                    $env:REVBOT_NEXT_LOCAL_BUILD_WORKAROUND = $previousNextWorkaround
                }
            }
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
