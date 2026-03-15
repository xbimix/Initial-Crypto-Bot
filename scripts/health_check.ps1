param(
    [string]$BaseUrl = "http://127.0.0.1:8001",
    [int]$TimeoutSec = 5,
    [switch]$IncludeStatus
)

$ErrorActionPreference = "Stop"
$repoRoot = Resolve-Path (Join-Path $PSScriptRoot "..")
$stateDir = Join-Path $repoRoot "crypto_bot\state"
$runtimeEventsPath = Join-Path $stateDir "runtime_events.jsonl"

function Write-RuntimeEvent {
    param(
        [Parameter(Mandatory = $true)][string]$EventType,
        [hashtable]$Fields = @{}
    )

    try {
        New-Item -ItemType Directory -Path $stateDir -Force | Out-Null
        $now = [DateTimeOffset]::UtcNow
        $payload = [ordered]@{
            event_type = $EventType
            time_utc = $now.ToString("o")
            day_utc = $now.ToString("yyyy-MM-dd")
            service = "health_check"
            pid = $PID
        }
        foreach ($key in $Fields.Keys) {
            $payload[$key] = $Fields[$key]
        }
        ($payload | ConvertTo-Json -Compress) + "`n" | Out-File -FilePath $runtimeEventsPath -Encoding utf8 -Append
    }
    catch {
        # Do not block health output on event logging errors.
    }
}

function Invoke-Endpoint {
    param(
        [Parameter(Mandatory = $true)][string]$Url,
        [Parameter(Mandatory = $true)][string]$Name,
        [int]$TimeoutSecLocal = 5
    )

    try {
        $response = Invoke-RestMethod -Uri $Url -Method Get -TimeoutSec $TimeoutSecLocal
        return [ordered]@{
            name = $Name
            ok = $true
            data = $response
            error = $null
        }
    }
    catch {
        return [ordered]@{
            name = $Name
            ok = $false
            data = $null
            error = $_.Exception.Message
        }
    }
}

$health = Invoke-Endpoint -Url "$BaseUrl/health" -Name "health" -TimeoutSecLocal $TimeoutSec
$ready = Invoke-Endpoint -Url "$BaseUrl/ready" -Name "ready" -TimeoutSecLocal $TimeoutSec

$results = @($health, $ready)
if ($IncludeStatus) {
    $results += Invoke-Endpoint -Url "$BaseUrl/status" -Name "status" -TimeoutSecLocal $TimeoutSec
}

$allOk = $true
foreach ($result in $results) {
    if ($result.ok) {
        Write-Host "[OK ] $($result.name)"
    }
    else {
        Write-Host "[ERR] $($result.name): $($result.error)"
        $allOk = $false
    }
}

if (-not $allOk) {
    $failed = @(
        $results |
        Where-Object { -not $_.ok } |
        ForEach-Object { $_.name }
    )
    Write-RuntimeEvent -EventType "health_check" -Fields @{
        ok = $false
        base_url = $BaseUrl
        include_status = [bool]$IncludeStatus
        failed_endpoints = $failed
    }
    exit 1
}

Write-RuntimeEvent -EventType "health_check" -Fields @{
    ok = $true
    base_url = $BaseUrl
    include_status = [bool]$IncludeStatus
}
