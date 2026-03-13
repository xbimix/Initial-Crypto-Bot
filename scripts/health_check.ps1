param(
    [string]$BaseUrl = "http://127.0.0.1:8001",
    [int]$TimeoutSec = 5,
    [switch]$IncludeStatus
)

$ErrorActionPreference = "Stop"

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
    exit 1
}
