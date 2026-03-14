param(
    [int]$SampleSeconds = 10,
    [switch]$SkipPythonBench
)

$ErrorActionPreference = "Stop"

$repoRoot = Resolve-Path (Join-Path $PSScriptRoot "..")
$stateDir = Join-Path $repoRoot "crypto_bot\state"
$botLog = Join-Path $stateDir "bot.log"

function Resolve-Python {
    $venvPython = Join-Path $repoRoot ".venv\Scripts\python.exe"
    if (Test-Path $venvPython) {
        return $venvPython
    }
    return "python"
}

Write-Host "== State File Sizes =="
if (-not (Test-Path $stateDir)) {
    throw "State directory not found: $stateDir"
}

Get-ChildItem -Path $stateDir -File |
    Select-Object Name, Length, LastWriteTime |
    Sort-Object Length -Descending |
    Format-Table -AutoSize

Write-Host ""
Write-Host "== Log Growth Sample (${SampleSeconds}s) =="
if (Test-Path $botLog) {
    $startBytes = (Get-Item $botLog).Length
    Start-Sleep -Seconds $SampleSeconds
    $endBytes = (Get-Item $botLog).Length
    $delta = $endBytes - $startBytes
    $rate = if ($SampleSeconds -gt 0) { [math]::Round($delta / $SampleSeconds, 2) } else { 0.0 }

    [pscustomobject]@{
        BytesStart = $startBytes
        BytesEnd = $endBytes
        BytesDelta = $delta
        BytesPerSecond = $rate
    } | Format-List
}
else {
    Write-Host "bot.log not found"
}

if ($SkipPythonBench) {
    Write-Host ""
    Write-Host "Skipped Python micro-benchmarks."
    exit 0
}

Write-Host ""
Write-Host "== Python Micro-Benchmarks =="
$pythonCmd = Resolve-Python

Push-Location (Join-Path $repoRoot "crypto_bot")
try {
    @'
import json
import os
import re
import statistics
import time
import shutil
from pathlib import Path

from utils.config_loader import load_config
from utils.state_io import read_json_file, write_json_file

state_dir = Path("state")
config_path = state_dir / "config.json"
paper_path = state_dir / "paper_state.json"
strategy_path = state_dir / "strategy_state.json"
trades_path = state_dir / "trades.json"
log_path = state_dir / "bot.log"

def bench(fn, n):
    timings = []
    for _ in range(n):
        t0 = time.perf_counter()
        fn()
        timings.append((time.perf_counter() - t0) * 1000.0)
    timings.sort()
    return {
        "n": n,
        "mean_ms": round(statistics.mean(timings), 4),
        "p50_ms": round(statistics.median(timings), 4),
        "p95_ms": round(timings[int(n * 0.95) - 1], 4),
        "max_ms": round(max(timings), 4),
    }

# Warm-up
_ = load_config()
_ = read_json_file(config_path, strict=True)
_ = read_json_file(paper_path, strict=True)
_ = read_json_file(strategy_path, strict=True)
_ = read_json_file(trades_path, strict=True)

results = {
    "load_config": bench(lambda: load_config(), 200),
    "read_config_json": bench(lambda: read_json_file(config_path, strict=True), 1000),
    "read_paper_state_json": bench(lambda: read_json_file(paper_path, strict=True), 1000),
    "read_strategy_state_json": bench(lambda: read_json_file(strategy_path, strict=True), 600),
    "read_trades_json": bench(lambda: read_json_file(trades_path, strict=True), 600),
}

cfg_payload = read_json_file(config_path, strict=True)
trades_payload = read_json_file(trades_path, strict=True)

bench_dir = state_dir / f".profile_tmp_{os.getpid()}"
bench_dir.mkdir(parents=True, exist_ok=True)

try:
    cfg_tmp = bench_dir / "config.json"
    trades_tmp = bench_dir / "trades.json"
    write_json_file(cfg_tmp, cfg_payload)
    write_json_file(trades_tmp, trades_payload)
    results["write_config_json_locked"] = bench(lambda: write_json_file(cfg_tmp, cfg_payload), 200)
    results["write_trades_json_locked"] = bench(lambda: write_json_file(trades_tmp, trades_payload), 120)
finally:
    shutil.rmtree(bench_dir, ignore_errors=True)

snapshot_pattern = re.compile(
    r"^(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}),\d+\s+\|\s+INFO\s+\|\s+SNAPSHOT\s+([A-Z0-9-]+)\s+\|\s+(.+)$"
)

def log_tail_parse():
    if not log_path.exists():
        return 0
    size = log_path.stat().st_size
    n = min(256 * 1024, size)
    if n <= 0:
        return 0
    with open(log_path, "rb") as handle:
        handle.seek(size - n)
        tail = handle.read(n).decode("utf-8", errors="ignore")
    count = 0
    for line in tail.splitlines():
        if snapshot_pattern.match(line):
            count += 1
    return count

results["log_tail_parse_256kb"] = bench(log_tail_parse, 200)

summary = {
    "state_files": {
        "config_bytes": config_path.stat().st_size if config_path.exists() else None,
        "paper_state_bytes": paper_path.stat().st_size if paper_path.exists() else None,
        "strategy_state_bytes": strategy_path.stat().st_size if strategy_path.exists() else None,
        "trades_bytes": trades_path.stat().st_size if trades_path.exists() else None,
        "bot_log_bytes": log_path.stat().st_size if log_path.exists() else None,
    },
    "benchmarks": results,
}

print(json.dumps(summary, indent=2))
'@ | & $pythonCmd -
}
finally {
    Pop-Location
}
