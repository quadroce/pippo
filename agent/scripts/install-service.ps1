<#
.SYNOPSIS
  Installs (or reinstalls) the Pippo agent as a Windows service using NSSM.

.DESCRIPTION
  The service runs `python -m pippo serve` from the agent's virtual environment, starts with
  Windows, restarts 5 seconds after any exit and writes logs to agent\logs\agent.log (rotated
  at 5 MB). Run from an elevated PowerShell. NSSM must be installed (`winget install NSSM.NSSM`)
  or its path passed with -NssmPath.

  By default the service runs as LocalSystem. Chrome profiles are then stored under the system
  account, not yours, and the VPN client must also be available to system services. If your VPN
  or Chrome only works in your user session, pass -Credential to run as your own account.

.PARAMETER ServiceName
  Windows service name. Default: PippoAgent (display name "Pippo Agent").

.PARAMETER NssmPath
  Full path to nssm.exe if it is not on PATH.

.PARAMETER Credential
  Optional account to run the service as, e.g. (Get-Credential). The password is handed to NSSM
  and never written by this script.

.PARAMETER DryRun
  Print what would be done without changing anything (no elevation needed).

.EXAMPLE
  .\scripts\install-service.ps1
  .\scripts\install-service.ps1 -Credential (Get-Credential)
  .\scripts\install-service.ps1 -DryRun
#>
[CmdletBinding()]
param(
    [string]$ServiceName = "PippoAgent",
    [string]$NssmPath,
    [System.Management.Automation.PSCredential]$Credential,
    [switch]$DryRun
)

$ErrorActionPreference = "Stop"

$AgentDir = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$Python = Join-Path $AgentDir ".venv\Scripts\python.exe"
$LogDir = Join-Path $AgentDir "logs"
$LogFile = Join-Path $LogDir "agent.log"
$DisplayName = "Pippo Agent"

function Fail($msg) { Write-Error $msg; exit 1 }

# --- Preconditions ---------------------------------------------------------------------------
if (-not $NssmPath) {
    $cmd = Get-Command nssm -ErrorAction SilentlyContinue
    if ($cmd) { $NssmPath = $cmd.Source }
}
if (-not $NssmPath -or -not (Test-Path $NssmPath)) {
    if ($DryRun) { $NssmPath = "nssm.exe"; Write-Warning "NSSM not found (dry run continues). Install: winget install NSSM.NSSM" }
    else { Fail "NSSM not found. Install it with 'winget install NSSM.NSSM' (then open a new terminal) or pass -NssmPath." }
}
if (-not (Test-Path $Python)) {
    if ($DryRun) { Write-Warning "Virtual environment missing at $Python (dry run continues)." } else {
    Fail "Virtual environment not found at $Python. Run: python -m venv .venv; .venv\Scripts\activate; pip install -r requirements.txt" }
}
if (-not (Test-Path (Join-Path $AgentDir ".env"))) {
    $envMsg = ".env not found in $AgentDir. Copy .env.example to .env and set API_BASE_URL and AGENT_API_KEY first."
    if ($DryRun) { Write-Warning "$envMsg (dry run continues)." } else { Fail $envMsg }
}
if (-not $DryRun) {
    $principal = New-Object Security.Principal.WindowsPrincipal([Security.Principal.WindowsIdentity]::GetCurrent())
    if (-not $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) {
        Fail "Run this script from an elevated (Administrator) PowerShell."
    }
}

# --- Actions ---------------------------------------------------------------------------------
function Nssm {
    param([Parameter(ValueFromRemainingArguments = $true)][string[]]$NssmArgs)
    if ($DryRun) { Write-Host "[dry-run] nssm $($NssmArgs -join ' ')"; return }
    & $NssmPath @NssmArgs | Out-Null
    if ($LASTEXITCODE -ne 0) { Fail "nssm $($NssmArgs -join ' ') failed with exit code $LASTEXITCODE" }
}

if (-not $DryRun) { New-Item -ItemType Directory -Force $LogDir | Out-Null }

$existing = if ($DryRun) { $null } else { Get-Service -Name $ServiceName -ErrorAction SilentlyContinue }
if ($existing) {
    Write-Host "Service $ServiceName already exists: reinstalling."
    if ($existing.Status -ne "Stopped") { Nssm stop $ServiceName }
    Nssm remove $ServiceName confirm
}

Write-Host "Installing $ServiceName -> $Python -m pippo serve"
Nssm install $ServiceName $Python "-m" "pippo" "serve"
Nssm set $ServiceName DisplayName $DisplayName
Nssm set $ServiceName Description "Pippo QoE agent: measures pluto.tv and reports to the Pippo web app."
Nssm set $ServiceName AppDirectory $AgentDir
Nssm set $ServiceName Start SERVICE_AUTO_START

# Restart policy: any exit (crash or stop of the process) restarts it after 5 s.
Nssm set $ServiceName AppExit Default Restart
Nssm set $ServiceName AppRestartDelay 5000
Nssm set $ServiceName AppThrottle 10000

# Logging with rotation.
Nssm set $ServiceName AppStdout $LogFile
Nssm set $ServiceName AppStderr $LogFile
Nssm set $ServiceName AppRotateFiles 1
Nssm set $ServiceName AppRotateOnline 1
Nssm set $ServiceName AppRotateBytes 5242880

# Unbuffered output so the log is readable in real time.
Nssm set $ServiceName AppEnvironmentExtra "PYTHONUNBUFFERED=1"

if ($Credential) {
    $user = $Credential.UserName
    $pass = $Credential.GetNetworkCredential().Password
    if ($DryRun) { Write-Host "[dry-run] nssm set $ServiceName ObjectName $user ********" }
    else { Nssm set $ServiceName ObjectName $user $pass }
}

if ($DryRun) {
    Write-Host "[dry-run] Start-Service $ServiceName"
} else {
    Start-Service -Name $ServiceName
    Start-Sleep -Seconds 3
    $svc = Get-Service -Name $ServiceName
    Write-Host "Service $ServiceName is $($svc.Status). Log: $LogFile"
    if ($svc.Status -ne "Running") { Fail "Service did not start; check $LogFile and the Windows event log." }
}

Write-Host "Done. Manage it from services.msc ('$DisplayName') or: Restart-Service $ServiceName"
