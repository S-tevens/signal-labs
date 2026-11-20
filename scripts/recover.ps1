<#
  Demo recovery (task E30): check the stack and undo the things that commonly go wrong during a demo.

    .\scripts\recover.ps1             # check everything, then put right what is safe to put right
    .\scripts\recover.ps1 -Restart    # also restart the whole stack (keeps data; takes about a minute)

  It restores the SaaS link if a scenario left it down, releases a hold left on in the egress panel, clears a stale
  pid file, and reports each component as OK or DOWN with the next step. It never prints credentials.
#>
param([switch]$Restart)
$root = Split-Path -Parent $PSScriptRoot
$envFile = Join-Path $root "data\run.env.json"
$saas = "https://127.0.0.1:8080"; $ca = ""
if (Test-Path $envFile) { $run = Get-Content $envFile -Raw | ConvertFrom-Json; if ($run.saas_url) { $saas = $run.saas_url }; if ($run.ca) { $ca = $run.ca } }
$pidFile = Join-Path $root "data\run.pids.json"

if ($Restart) {
  # Stop what the pid file knows about first. Only then free the stack's ports, in case a start was interrupted and
  # the pid file is stale or empty (deleting it first would leave the old processes running and the new ones unable
  # to bind), and finally drop the file.
  & (Join-Path $PSScriptRoot "stop-local.ps1") 2>&1 | Out-Null
  Get-NetTCPConnection -State Listen -LocalPort 8000, 8001, 8080, 8101, 5173 -ErrorAction SilentlyContinue |
    ForEach-Object { Stop-Process -Id $_.OwningProcess -Force -ErrorAction SilentlyContinue }
  Start-Sleep -Seconds 2
  if (Test-Path $pidFile) { Remove-Item $pidFile -Force }
  $opts = @{ Restart = $true; NoSimulator = $true }   # a hashtable splats as named switches; an array would be positional
  if ($ca) { $opts["Tls"] = $true }
  & (Join-Path $PSScriptRoot "run-local.ps1") @opts 2>&1 | Out-Null
}

function Test-Http($url) { try { $null = Invoke-WebRequest -Uri $url -UseBasicParsing -TimeoutSec 4; return $true } catch { return $false } }
function Report($name, $ok, $next) { $mark = if ($ok) { "OK  " } else { "DOWN" }; Write-Host ("  {0}  {1}" -f $mark, $name) -ForegroundColor $(if ($ok) { "Green" } else { "Red" }); if (-not $ok) { Write-Host "        next: $next" } }

Write-Host "Checking the stack ..."
$collector = Test-Http "http://127.0.0.1:8101/healthz"
Report "collector            http://127.0.0.1:8101" $collector ".\scripts\recover.ps1 -Restart"
if ($collector) {
  $buf = Invoke-RestMethod "http://127.0.0.1:8101/local/buffer"
  if ($buf.link -ne "up") { $null = Invoke-RestMethod -Method Post "http://127.0.0.1:8101/local/saas-link/up"; Write-Host "  FIXED  the SaaS link was down; it is up again" -ForegroundColor Yellow }
  if ($buf.hold.held) { $null = Invoke-RestMethod -Method Post "http://127.0.0.1:8101/local/release" -Headers @{ "X-Requested-With" = "local-ui" }; Write-Host "  FIXED  sending was held; released (the buffered payloads will go now)" -ForegroundColor Yellow }
  Write-Host ("        waiting to send: {0}; last error: {1}" -f $buf.pending, $(if ($buf.last_error) { $buf.last_error } else { "none" }))
}
# The SaaS endpoints use a private CA in dev, so check that the port accepts connections (a certificate check is the
# collector's job and is shown in the egress panel).
function Test-Port($port) { try { $c = New-Object System.Net.Sockets.TcpClient; $c.Connect("127.0.0.1", $port); $c.Close(); return $true } catch { return $false } }
$saasPort = ([uri]$saas).Port
Report "SaaS entry point     $saas" (Test-Port $saasPort) ".\scripts\recover.ps1 -Restart"
Report "SaaS replica 1       127.0.0.1:8000" (Test-Port 8000) "one replica down is survivable (the proxy fails over); bring it back with .\scripts\recover.ps1 -Restart"
Report "SaaS replica 2       127.0.0.1:8001" (Test-Port 8001) "one replica down is survivable (the proxy fails over); bring it back with .\scripts\recover.ps1 -Restart"
Report "dashboard            http://127.0.0.1:5173" (Test-Http "http://127.0.0.1:5173") "start it with .\scripts\run-local.ps1 (without -NoDashboard), or open the egress panel and the API directly"
$pg = $false; try { $c = New-Object System.Net.Sockets.TcpClient; $c.Connect("127.0.0.1", 5433); $pg = $true; $c.Close() } catch { }
Report "Postgres            127.0.0.1:5433" $pg ".\scripts\recover.ps1 -Restart (data is kept in data\pg)"
Write-Host "Done. If a scenario misbehaves, wait 2 minutes between scenarios on the same host (correlation window) or use a fresh host."
