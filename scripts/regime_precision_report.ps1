param(
    [string]$StateDir = "",
    [string]$OutFile = "",
    [switch]$SummaryOnly
)

$ErrorActionPreference = "Stop"

$repoRoot = Resolve-Path (Join-Path $PSScriptRoot "..")
$venvPython = Join-Path $repoRoot ".venv\Scripts\python.exe"
$pythonCmd = if (Test-Path $venvPython) { $venvPython } else { "python" }

if (-not $StateDir) {
    $StateDir = Join-Path $repoRoot "crypto_bot\state"
}

$scriptPath = Join-Path $repoRoot "scripts\regime_precision_report.py"
if (-not (Test-Path $scriptPath)) {
    throw "Report script not found: $scriptPath"
}

$args = @(
    $scriptPath
    "--state-dir"
    $StateDir
)

if ($SummaryOnly) {
    $args += "--summary-only"
}

if ($OutFile) {
    $args += "--out"
    $args += $OutFile
}

& $pythonCmd @args

if ($LASTEXITCODE -ne 0) {
    throw "Regime precision report failed (exit code $LASTEXITCODE)"
}
