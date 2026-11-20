<#
  Make the development TLS certificates (a private CA and a server certificate signed by it).

    .\scripts\gen-certs.ps1                       # writes data\certs\ca.pem, server.pem and their keys
    .\scripts\gen-certs.ps1 -Force                # replace existing certificates
    .\scripts\gen-certs.ps1 -San saas.internal    # also cover another host name or IP

  DEV ONLY. The keys are unprotected files under data\ (git-ignored). Use real certificates in production.
  run-local.ps1 -Tls calls this for you.
#>
param([switch]$Force, [string[]]$San = @())
$root = Split-Path -Parent $PSScriptRoot
$python = if ($env:PYTHON) { $env:PYTHON } else { "python" }
$argList = @("-m", "collector.devcerts", "--out", (Join-Path $root "data\certs"))
foreach ($s in $San) { $argList += @("--san", $s) }
if ($Force) { $argList += "--force" }
Set-Location $root
& $python @argList
