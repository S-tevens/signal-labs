<#
  Run one live scenario against the local stack.

    .\scripts\demo.ps1 -List
    .\scripts\demo.ps1 failed-logins
    .\scripts\demo.ps1 outage

  Scenarios: secret, outage, failed-logins, latency, cpu-spike, packet-loss, disk, alert-storm, delivery, remediation.
  Each prints what to expect, injects the event, then shows what the SaaS did.
  Run a steady stream first so the SaaS has a baseline:  python simulator\generator.py --seconds 120
#>
param(
  [Parameter(Position = 0)][string]$Scenario,
  [switch]$List
)
$root = Split-Path -Parent $PSScriptRoot
$python = if ($env:PYTHON) { $env:PYTHON } else { "python" }
# run-local.ps1 -Tls leaves a marker naming the CA; talk HTTPS to the SaaS when it is there.
$marker = Join-Path $root "data\run.tls"
if (Test-Path $marker) {
  $env:SAAS_URL = "https://127.0.0.1:8000"
  $env:SAAS_CA_FILE = (Get-Content $marker -Raw).Trim()
}
if ($List -or -not $Scenario) { & $python "$root\simulator\scenarios.py" --list; exit 0 }
& $python "$root\simulator\scenarios.py" $Scenario
