param(
  [double]$Hours = 12
)

$python = Join-Path $PSScriptRoot "..\.venv\Scripts\python.exe"
$tool = Join-Path $PSScriptRoot "..\crypto_bot\tools\live_safety_tuning_report.py"
$state = Join-Path $PSScriptRoot "..\crypto_bot\state"

& $python $tool --state-dir $state --hours $Hours
exit $LASTEXITCODE

