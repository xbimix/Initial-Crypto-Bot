param(
  [switch]$DryRun,
  [int]$DuplicateThreshold = 3
)

$python = Join-Path $PSScriptRoot "..\.venv\Scripts\python.exe"
$tool = Join-Path $PSScriptRoot "..\crypto_bot\tools\repair_core_candles.py"
$state = Join-Path $PSScriptRoot "..\crypto_bot\state"
$pkgRoot = Join-Path $PSScriptRoot "..\crypto_bot"

$args = @($tool, "--state-dir", $state, "--duplicate-threshold", $DuplicateThreshold)
if ($DryRun) {
  $args += "--dry-run"
}

if ([string]::IsNullOrWhiteSpace($env:PYTHONPATH)) {
  $env:PYTHONPATH = $pkgRoot
} else {
  $env:PYTHONPATH = "$pkgRoot;$($env:PYTHONPATH)"
}

& $python @args
exit $LASTEXITCODE
