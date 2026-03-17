param(
    [string]$KeysDir = "D:\Python-Codes\RevBot\revolut-keys",
    [switch]$ApplyFix
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

function Write-Status {
    param(
        [string]$Level,
        [string]$Message
    )
    Write-Host ("[{0}] {1}" -f $Level, $Message)
}

function Get-SafePrincipals {
    $currentUser = "{0}\{1}" -f $env:USERDOMAIN, $env:USERNAME
    return @(
        $currentUser.ToUpperInvariant(),
        "BUILTIN\ADMINISTRATORS",
        "NT AUTHORITY\SYSTEM"
    )
}

function Test-PathSecure {
    param([string]$Path)

    if (-not (Test-Path -LiteralPath $Path -PathType Leaf)) {
        return @{
            path = $Path
            exists = $false
            issues = @("missing_file")
            acl = $null
        }
    }

    $issues = @()
    $acl = Get-Acl -LiteralPath $Path
    $safePrincipals = Get-SafePrincipals

    if ($acl.AreAccessRulesProtected -eq $false) {
        $issues += "inheritance_enabled"
    }

    foreach ($rule in $acl.Access) {
        $identity = [string]$rule.IdentityReference
        $identityUpper = $identity.ToUpperInvariant()
        $rights = [string]$rule.FileSystemRights
        $isAllow = $rule.AccessControlType -eq "Allow"
        $hasReadLike = $rights -match "Read" -or $rights -match "FullControl" -or $rights -match "Modify" -or $rights -match "Write"
        if ($isAllow -and $hasReadLike -and ($safePrincipals -notcontains $identityUpper)) {
            $issues += "unexpected_principal:$identity"
        }
    }

    return @{
        path = $Path
        exists = $true
        issues = $issues
        acl = $acl
    }
}

function Protect-PathAcl {
    param([string]$Path)

    $safePrincipals = Get-SafePrincipals
    $currentUser = $safePrincipals[0]

    $acl = Get-Acl -LiteralPath $Path
    $acl.SetAccessRuleProtection($true, $false)

    foreach ($rule in @($acl.Access)) {
        [void]$acl.RemoveAccessRuleAll($rule)
    }

    $inheritance = [System.Security.AccessControl.InheritanceFlags]::None
    $propagation = [System.Security.AccessControl.PropagationFlags]::None

    $rules = @(
        (New-Object -TypeName System.Security.AccessControl.FileSystemAccessRule -ArgumentList @(
            $currentUser,
            "FullControl",
            $inheritance,
            $propagation,
            [System.Security.AccessControl.AccessControlType]::Allow
        )),
        (New-Object -TypeName System.Security.AccessControl.FileSystemAccessRule -ArgumentList @(
            "BUILTIN\Administrators",
            "FullControl",
            $inheritance,
            $propagation,
            [System.Security.AccessControl.AccessControlType]::Allow
        )),
        (New-Object -TypeName System.Security.AccessControl.FileSystemAccessRule -ArgumentList @(
            "NT AUTHORITY\SYSTEM",
            "FullControl",
            $inheritance,
            $propagation,
            [System.Security.AccessControl.AccessControlType]::Allow
        ))
    )

    foreach ($rule in $rules) {
        [void]$acl.AddAccessRule($rule)
    }

    Set-Acl -LiteralPath $Path -AclObject $acl
}

$targetFiles = @(
    (Join-Path $KeysDir "api_key.txt"),
    (Join-Path $KeysDir "private.pem"),
    (Join-Path $KeysDir "public.pem")
)

Write-Status "INFO" ("Auditing Revolut key files in {0}" -f $KeysDir)

$anyIssues = $false
foreach ($file in $targetFiles) {
    $result = Test-PathSecure -Path $file
    if (-not $result.exists) {
        Write-Status "WARN" ("Missing key file: {0}" -f $file)
        $anyIssues = $true
        continue
    }

    if ($result.issues.Count -eq 0) {
        Write-Status "OK" ("{0} ACL is restricted" -f $file)
    } else {
        Write-Status "WARN" ("{0} issues: {1}" -f $file, ($result.issues -join ", "))
        $anyIssues = $true
        if ($ApplyFix) {
            Write-Status "INFO" ("Applying ACL hardening to {0}" -f $file)
            Protect-PathAcl -Path $file
            Write-Status "OK" ("ACL hardened for {0}" -f $file)
        }
    }
}

if ($ApplyFix) {
    Write-Status "INFO" "Re-run without -ApplyFix to verify final ACL posture."
} elseif ($anyIssues) {
    Write-Status "INFO" "Run with -ApplyFix to restrict ACLs to current user + Administrators + SYSTEM."
}
