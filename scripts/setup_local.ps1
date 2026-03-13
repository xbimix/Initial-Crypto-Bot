param(
    [switch]$SkipWebInstall,
    [switch]$InstallDev
)

$ErrorActionPreference = "Stop"

$repoRoot = Resolve-Path (Join-Path $PSScriptRoot "..")
$venvPython = Join-Path $repoRoot ".venv\Scripts\python.exe"
$requirements = Join-Path $repoRoot "crypto_bot\requirements.txt"
$requirementsDev = Join-Path $repoRoot "crypto_bot\requirements-dev.txt"
$webUiDir = Join-Path $repoRoot "web-ui"

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
    if (-not (Test-Path $venvPython)) {
        Write-Host "Creating virtual environment..."
        Invoke-Checked -Command "py" -Arguments @("-3", "-m", "venv", ".venv")
    }

    Invoke-Checked -Command $venvPython -Arguments @("-m", "pip", "install", "--upgrade", "pip")
    if ($InstallDev) {
        Invoke-Checked -Command $venvPython -Arguments @("-m", "pip", "install", "-r", $requirementsDev)
    }
    else {
        Invoke-Checked -Command $venvPython -Arguments @("-m", "pip", "install", "-r", $requirements)
    }

    if (-not $SkipWebInstall) {
        Push-Location $webUiDir
        try {
            Invoke-Checked -Command "npm" -Arguments @("install")
        }
        finally {
            Pop-Location
        }
    }
}
finally {
    Pop-Location
}

Write-Host "Local setup complete."
Write-Host "Run bot: .\\.venv\\Scripts\\python.exe .\\crypto_bot\\main.py"
Write-Host "Run UI:  cd .\\web-ui ; npm run dev"
