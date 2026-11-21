<#
  Start the demo from a clean slate: no leftover test collectors, incidents or payloads, everything Good and live.

    .\scripts\reset-demo.ps1                  # TLS, simulator and dashboard on (the normal demo)
    .\scripts\reset-demo.ps1 -AcceptPush      # also let the organizers push to this collector
    .\scripts\reset-demo.ps1 -NoSimulator     # no simulated data (for a measurement or an organizer-fed run)

  It stops the stack, deletes the database and the collector's local store and the scratch demo folders, then starts
  everything again. Kept: certificates, the session secret, the ingest token and the development sign-ins (the users are
  recreated with the same passwords). Evidence files in docs\p3\evidence are untouched. Give the simulator about two
  minutes before showing the dashboard: the platform needs a baseline before it scores deviations.
#>
param([switch]$AcceptPush, [switch]$NoSimulator, [switch]$NoDashboard)
$root = Split-Path -Parent $PSScriptRoot
Set-Location $root
Write-Host "Stopping the stack ..."
& (Join-Path $PSScriptRoot "stop-local.ps1") 2>&1 | Out-Null
Get-NetTCPConnection -State Listen -LocalPort 8000, 8001, 8080, 8101, 5173 -ErrorAction SilentlyContinue |
  ForEach-Object { Stop-Process -Id $_.OwningProcess -Force -ErrorAction SilentlyContinue }
Start-Sleep -Seconds 3
Write-Host "Clearing demo data ..."
foreach ($d in "pg", "collector", "flood-demo", "stream-demo", "enroll-demo", "pg.log", "run.pids.json", "run.env.json") {
  $p = Join-Path $root "data\$d"
  if (Test-Path $p) { Remove-Item $p -Recurse -Force -ErrorAction SilentlyContinue }
}
$opts = @{ Tls = $true }
if ($AcceptPush) { $opts["AcceptPush"] = $true }
if ($NoSimulator) { $opts["NoSimulator"] = $true }
if ($NoDashboard) { $opts["NoDashboard"] = $true }
Write-Host "Starting the stack ..."
& (Join-Path $PSScriptRoot "run-local.ps1") @opts
