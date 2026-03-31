param(
    [switch]$SkipWebBuild
)

$ErrorActionPreference = "Stop"
$repoRoot = Resolve-Path (Join-Path $PSScriptRoot "..")
$venvPython = Join-Path $repoRoot ".venv\Scripts\python.exe"
$configPath = Join-Path $repoRoot "crypto_bot\state\config.json"

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
    # Strict deployment posture for mutating auth and config normalization.
    $previousDeploymentMode = $env:REVBOT_DEPLOYMENT_MODE
    $previousStrictAuth = $env:REVBOT_STRICT_MUTATING_AUTH
    $previousStrictConfig = $env:REVBOT_CONFIG_STRICT
    $previousAutosaveConfig = $env:REVBOT_CONFIG_AUTOSAVE_NORMALIZED
    $env:REVBOT_DEPLOYMENT_MODE = "1"
    $env:REVBOT_STRICT_MUTATING_AUTH = "1"
    $env:REVBOT_CONFIG_STRICT = "1"
    $env:REVBOT_CONFIG_AUTOSAVE_NORMALIZED = "1"

    try {
        # Persist normalized defaults (including paper_execution + sizing keys).
        Invoke-Checked -Command $venvPython -Arguments @(
            "-c",
            "from crypto_bot.utils.config_loader import load_config, save_config; c=load_config(); save_config(c)"
        )

        # Safe deploy arm state: require explicit user arming after deploy.
        $configPathPy = $configPath -replace "\\", "/"
        Invoke-Checked -Command $venvPython -Arguments @(
            "-c",
            "from pathlib import Path; from crypto_bot.utils.state_io import read_json_file, write_json_file; p=Path(r'" + $configPathPy + "'); cfg=read_json_file(p, strict=True); cfg['trading_enabled']=False; cfg['enabled']=False; write_json_file(p, cfg)"
        )

        # Full local go/no-go.
        if ($SkipWebBuild) {
            & "$PSScriptRoot\check_local.ps1" -SkipWebBuild
        }
        else {
            & "$PSScriptRoot\check_local.ps1"
        }
        if (-not $?) {
            throw "check_local.ps1 failed"
        }
    }
    finally {
        if ($null -eq $previousDeploymentMode) { Remove-Item Env:REVBOT_DEPLOYMENT_MODE -ErrorAction SilentlyContinue } else { $env:REVBOT_DEPLOYMENT_MODE = $previousDeploymentMode }
        if ($null -eq $previousStrictAuth) { Remove-Item Env:REVBOT_STRICT_MUTATING_AUTH -ErrorAction SilentlyContinue } else { $env:REVBOT_STRICT_MUTATING_AUTH = $previousStrictAuth }
        if ($null -eq $previousStrictConfig) { Remove-Item Env:REVBOT_CONFIG_STRICT -ErrorAction SilentlyContinue } else { $env:REVBOT_CONFIG_STRICT = $previousStrictConfig }
        if ($null -eq $previousAutosaveConfig) { Remove-Item Env:REVBOT_CONFIG_AUTOSAVE_NORMALIZED -ErrorAction SilentlyContinue } else { $env:REVBOT_CONFIG_AUTOSAVE_NORMALIZED = $previousAutosaveConfig }
    }
}
finally {
    Pop-Location
}

Write-Host "Deployment readiness checks passed (strict mode + safe arm state)."
