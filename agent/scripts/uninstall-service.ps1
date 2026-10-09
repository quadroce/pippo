<#
.SYNOPSIS
  Stops and removes the Pippo agent Windows service. Run from an elevated PowerShell.
#>
[CmdletBinding()]
param(
    [string]$ServiceName = "PippoAgent",
    [string]$NssmPath
)

$ErrorActionPreference = "Stop"

if (-not $NssmPath) {
    $cmd = Get-Command nssm -ErrorAction SilentlyContinue
    if ($cmd) { $NssmPath = $cmd.Source }
}
if (-not $NssmPath -or -not (Test-Path $NssmPath)) { Write-Error "NSSM not found; pass -NssmPath."; exit 1 }

$principal = New-Object Security.Principal.WindowsPrincipal([Security.Principal.WindowsIdentity]::GetCurrent())
if (-not $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) {
    Write-Error "Run this script from an elevated (Administrator) PowerShell."; exit 1
}

$svc = Get-Service -Name $ServiceName -ErrorAction SilentlyContinue
if (-not $svc) { Write-Host "Service $ServiceName is not installed."; exit 0 }
if ($svc.Status -ne "Stopped") { & $NssmPath stop $ServiceName | Out-Null }
& $NssmPath remove $ServiceName confirm | Out-Null
if ($LASTEXITCODE -ne 0) { Write-Error "nssm remove failed with exit code $LASTEXITCODE"; exit 1 }
Write-Host "Service $ServiceName removed. Logs in agent\logs are kept."
