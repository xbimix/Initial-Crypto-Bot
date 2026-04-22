param(
  [double]$Hours = 24
)

$python = Join-Path $PSScriptRoot "..\.venv\Scripts\python.exe"
$tool = Join-Path $PSScriptRoot "..\crypto_bot\tools\sync_health_report.py"
$state = Join-Path $PSScriptRoot "..\crypto_bot\state"

& $python $tool --state-dir $state --hours $Hours
exit $LASTEXITCODE

