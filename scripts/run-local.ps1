<#
  Start the whole stack locally with one command (no Docker):

    .\scripts\run-local.ps1                 # Postgres, migration, 2 SaaS replicas, collector, simulator, dashboard
    .\scripts\run-local.ps1 -NoSimulator    # leave the data stream to you or the organizer's feed
    .\scripts\run-local.ps1 -NoDashboard
    .\scripts\run-local.ps1 -Restart        # stop anything already running first
    .\scripts\run-local.ps1 -Status         # show what is running

  Stop it with .\scripts\stop-local.ps1

  Needs: Python 3.11+ with the dependencies installed
           pip install -r collector\requirements.txt -r saas\requirements.txt
         PostgreSQL 16+ (the bin folder is found automatically, or set $env:PG_BIN)
         Node 20+ for the dashboard (npm ci runs on first start)

  Everything runs on dev credentials and plain HTTP. Never reuse these values outside a local demo.
  Data and logs live in .\data (git-ignored). Postgres uses port 5433 so it does not clash with an existing install.
#>
param(
  [switch]$NoSimulator,
  [switch]$NoDashboard,
  [switch]$Restart,
  [switch]$Status,
  [switch]$Tls,               # HTTPS between collector and SaaS, with a private dev CA (needs: pip install cryptography)
  [switch]$NoHostTelemetry,   # do not read this machine's CPU, memory, disk, bandwidth or probe the network
  [switch]$NoProxy            # send straight to replica 1 instead of through the failover proxy (port 8080)
)

# Windows PowerShell 5.1 turns any stderr text from a native command into a hard error under "Stop",
# which hides our own messages. We check exit codes explicitly instead.
$ErrorActionPreference = "Continue"
$root = Split-Path -Parent $PSScriptRoot
Set-Location $root

$data = Join-Path $root "data"
$logs = Join-Path $data "logs"
$pgData = Join-Path $data "pg"
$pidFile = Join-Path $data "run.pids.json"
$pgPort = 5433
$python = if ($env:PYTHON) { $env:PYTHON } else { "python" }

function Get-PgBin {
  if ($env:PG_BIN -and (Test-Path (Join-Path $env:PG_BIN "pg_ctl.exe"))) { return $env:PG_BIN }
  $found = Get-ChildItem "C:\Program Files\PostgreSQL\*\bin\pg_ctl.exe" -ErrorAction SilentlyContinue |
    Sort-Object { [int](($_.Directory.Parent.Name -replace '[^\d]', '')) } -Descending | Select-Object -First 1
  if ($found) { return $found.Directory.FullName }
  throw "PostgreSQL not found. Install PostgreSQL or set `$env:PG_BIN to its bin folder."
}

function Test-Alive($id) { return [bool](Get-Process -Id $id -ErrorAction SilentlyContinue) }

function Get-Running {
  if (-not (Test-Path $pidFile)) { return @() }
  $saved = Get-Content $pidFile -Raw | ConvertFrom-Json
  return @($saved | Where-Object { Test-Alive $_.pid })
}

function Wait-Url($url, $seconds = 40) {
  $end = (Get-Date).AddSeconds($seconds)
  $uri = [Uri]$url
  while ((Get-Date) -lt $end) {
    if ($uri.Scheme -eq "https") {
      # A private dev CA is not in Windows' trust store, so check that the TLS port accepts connections.
      try { $c = New-Object Net.Sockets.TcpClient; $c.Connect($uri.Host, $uri.Port); $c.Close(); return $true } catch { Start-Sleep -Milliseconds 700 }
    } else {
      try { Invoke-WebRequest -Uri $url -UseBasicParsing -TimeoutSec 2 | Out-Null; return $true } catch { Start-Sleep -Milliseconds 700 }
    }
  }
  return $false
}

if ($Status) {
  $running = Get-Running
  if (-not $running) { "Nothing is running." } else { $running | Format-Table name, pid, url -AutoSize }
  exit 0
}

if (Get-Running) {
  if ($Restart) { & (Join-Path $PSScriptRoot "stop-local.ps1") -KeepDb } else {
    Write-Host "Already running. Use -Restart, or .\scripts\stop-local.ps1 first." -ForegroundColor Yellow
    & $PSCommandPath -Status
    exit 0
  }
}

# ---- prerequisites ----
$pgBin = Get-PgBin
& $python -c "import fastapi, uvicorn, psycopg, yaml, httpx, pydantic" 2>&1 | Out-Null
if ($LASTEXITCODE -ne 0) {
  Write-Host "Python dependencies are missing for '$python'. Run:" -ForegroundColor Red
  Write-Host "  pip install -r collector\requirements.txt -r saas\requirements.txt"
  Write-Host "or point `$env:PYTHON at a Python that has them."
  exit 1
}
New-Item -ItemType Directory -Force $logs | Out-Null

# ---- Postgres ----
$pgReady = { & (Join-Path $pgBin "pg_isready.exe") -h localhost -p $pgPort 2>$null | Out-Null; $LASTEXITCODE -eq 0 }
if (-not (Test-Path (Join-Path $pgData "PG_VERSION"))) {
  Write-Host "Creating a local Postgres cluster in data\pg ..."
  & (Join-Path $pgBin "initdb.exe") -D $pgData -U postgres --auth=trust -E UTF8 2>&1 | Out-File (Join-Path $logs "initdb.log")
  if ($LASTEXITCODE -ne 0) { Write-Host "initdb failed; see data\logs\initdb.log" -ForegroundColor Red; exit 1 }
}
if (-not (& $pgReady)) {
  Write-Host "Starting Postgres on port $pgPort ..."
  # Start-Process with files, not pipes: Postgres must not inherit this shell's output handles.
  Start-Process -FilePath (Join-Path $pgBin "pg_ctl.exe") -WindowStyle Hidden `
    -ArgumentList @("start", "-D", "`"$pgData`"", "-o", "`"-p $pgPort`"", "-l", "`"$(Join-Path $logs 'pg.log')`"") `
    -RedirectStandardOutput (Join-Path $logs "pg_ctl.out") -RedirectStandardError (Join-Path $logs "pg_ctl.err")
  $end = (Get-Date).AddSeconds(40)
  while (-not (& $pgReady) -and (Get-Date) -lt $end) { Start-Sleep -Milliseconds 700 }
  if (-not (& $pgReady)) { Write-Host "Postgres did not start; see data\logs\pg.log" -ForegroundColor Red; exit 1 }
}
$exists = (& (Join-Path $pgBin "psql.exe") -h localhost -p $pgPort -U postgres -tAc "SELECT 1 FROM pg_database WHERE datname='signal'") 2>$null
if ("$exists".Trim() -ne "1") {
  & (Join-Path $pgBin "createdb.exe") -h localhost -p $pgPort -U postgres signal
}

# ---- schema (idempotent) ----
$env:ADMIN_DATABASE_URL = "postgresql://postgres@localhost:$pgPort/signal"
$env:SAAS_DB_PASSWORD = "dev_app_password"
& $python -m saas.migrate
if ($LASTEXITCODE -ne 0) { Write-Host "Migration failed." -ForegroundColor Red; exit 1 }

# ---- shared dev settings (never reuse these outside a local demo) ----
$env:DATABASE_URL = "postgresql://signal_app:dev_app_password@localhost:$pgPort/signal"
$env:REGION = "in"
if (-not $env:SAAS_AUTH_JSON) {
  $env:SAAS_AUTH_JSON = '{"collectors":{"key-acme-1":{"tenant":"t-acme","region":"in","collector":"col-blr-01","secret":"dev-secret-acme"}},"dashboard":{"dash-acme":{"tenant":"t-acme","region":"in","role":"operator"}}}'
}
$scheme = "http"
$envFile = Join-Path $data "run.env.json"   # how demo.ps1 finds the SaaS entry point and CA
Remove-Item $envFile -Force -ErrorAction SilentlyContinue
$proxyArgs = @()
$tlsArgs = @()
if ($Tls) {
  & $python -c "import cryptography" 2>&1 | Out-Null
  if ($LASTEXITCODE -ne 0) { Write-Host "-Tls needs the 'cryptography' package: pip install cryptography" -ForegroundColor Red; exit 1 }
  & $python -m collector.devcerts --out (Join-Path $data "certs") | Out-Null
  $certs = Join-Path $data "certs"
  $scheme = "https"
  $tlsArgs = @("--ssl-keyfile", (Join-Path $certs "server.key"), "--ssl-certfile", (Join-Path $certs "server.pem"))
  $env:SAAS_CA_FILE = Join-Path $certs "ca.pem"
  $env:REQUIRE_TLS = "1"
  $env:NODE_EXTRA_CA_CERTS = $env:SAAS_CA_FILE          # lets the dashboard's dev proxy trust the dev CA
  $proxyArgs = @("--ca", $env:SAAS_CA_FILE, "--tls-cert", (Join-Path $certs "server.pem"), "--tls-key", (Join-Path $certs "server.key"))
} else {
  Remove-Item Env:SAAS_CA_FILE, Env:REQUIRE_TLS -ErrorAction SilentlyContinue
}
# Everything (collector, dashboard, demo scenarios) enters the SaaS through the failover proxy unless -NoProxy.
$entryPort = if ($NoProxy) { 8000 } else { 8080 }
$saasUrl = "${scheme}://127.0.0.1:$entryPort"
$env:SAAS_PROXY_TARGET = $saasUrl           # where the dashboard's dev server forwards /api
@{ saas_url = $saasUrl; ca = $env:SAAS_CA_FILE } | ConvertTo-Json | Set-Content $envFile -Encoding ascii
$env:HOST_TELEMETRY = if ($NoHostTelemetry) { "0" } else { "1" }
# Services worth watching on this machine, reported as service_up (override with $env:SERVICE_CHECKS).
if (-not $env:SERVICE_CHECKS) {
  $env:SERVICE_CHECKS = "saas-1=127.0.0.1:8000,saas-2=127.0.0.1:8001,postgres=127.0.0.1:$pgPort" + $(if (-not $NoProxy) { ",lb=127.0.0.1:8080" } else { "" })
}

$started = New-Object System.Collections.ArrayList
function Start-Svc($name, $file, $argList, $url, $workdir = $root) {
  $out = Join-Path $logs "$name.out.log"
  $err = Join-Path $logs "$name.err.log"
  $p = Start-Process -FilePath $file -ArgumentList $argList -WorkingDirectory $workdir -WindowStyle Hidden -PassThru `
    -RedirectStandardOutput $out -RedirectStandardError $err
  [void]$started.Add([pscustomobject]@{ name = $name; pid = $p.Id; url = $url })
}

Write-Host "Starting services ..."
$env:REPLICA_ID = "1"; Start-Svc "saas-1" $python (@("-m", "uvicorn", "saas.main:app", "--port", "8000") + $tlsArgs) "${scheme}://127.0.0.1:8000/healthz"
$env:REPLICA_ID = "2"; Start-Svc "saas-2" $python (@("-m", "uvicorn", "saas.main:app", "--port", "8001") + $tlsArgs) "${scheme}://127.0.0.1:8001/healthz"

if (-not $NoProxy) {
  # Round-robin with failover; forwards the exact request bytes, so the collector's signatures still verify.
  $lbArgs = @("scripts\lb.py", "--listen", "127.0.0.1:8080", "--upstream", "${scheme}://127.0.0.1:8000", "--upstream", "${scheme}://127.0.0.1:8001") + $proxyArgs
  $lbHealth = if ($Tls) { "https://127.0.0.1:8080/_lb/status" } else { "http://127.0.0.1:8080/_lb/status" }
  Start-Svc "lb" $python $lbArgs $lbHealth
}

$env:SAAS_URL = $saasUrl
$env:DATA_DIR = (Join-Path $data "collector")
$env:HEARTBEAT_INTERVAL_S = "5"
Start-Svc "collector" $python @("-m", "uvicorn", "collector.main:app", "--port", "8101") "http://127.0.0.1:8101/healthz"

if (-not $NoDashboard) {
  $dash = Join-Path $root "dashboard"
  if (-not (Test-Path (Join-Path $dash "node_modules"))) {
    Write-Host "Installing dashboard dependencies (first run) ..."
    Push-Location $dash; npm ci --no-audit --no-fund | Out-Null; Pop-Location
  }
  if (-not (Test-Path (Join-Path $dash ".env.local"))) { "VITE_DASHBOARD_TOKEN=dash-acme" | Set-Content (Join-Path $dash ".env.local") -Encoding ascii }
  Start-Svc "dashboard" "npm.cmd" @("run", "dev") "http://127.0.0.1:5173" $dash
}

# Save the process list before waiting, so stop-local can always clean up.
$started | ConvertTo-Json | Set-Content $pidFile -Encoding ascii

$ok = $true
foreach ($s in $started) {
  if (-not (Wait-Url $s.url)) { $ok = $false; Write-Host "  NOT READY: $($s.name) ($($s.url)); see data\logs\$($s.name).err.log" -ForegroundColor Red }
}

if (-not $NoSimulator -and $ok) {
  Start-Svc "simulator" $python @("simulator\generator.py", "--seconds", "3600") ""
  $started | ConvertTo-Json | Set-Content $pidFile -Encoding ascii
}

Write-Host ""
if ($ok) { Write-Host "Stack is up." -ForegroundColor Green } else { Write-Host "Some services did not start." -ForegroundColor Red }
@(
  @{ n = "Dashboard"; u = "http://127.0.0.1:5173" },
  @{ n = "SaaS entry point"; u = "$saasUrl" + $(if ($NoProxy) { "  (replica 1 directly, no failover)" } else { "  (failover proxy; status at /_lb/status)" }) },
  @{ n = "SaaS replica 1 / 2"; u = "${scheme}://127.0.0.1:8000 and ${scheme}://127.0.0.1:8001" + $(if ($Tls) { "  (TLS, CA: data\certs\ca.pem)" } else { "  (plain HTTP)" }) },
  @{ n = "Collector"; u = "http://127.0.0.1:8101  (local only: /local/ui, /local/raw, /local/egress, /local/policy, /local/host)" },
  @{ n = "Logs"; u = "data\logs" }
) | ForEach-Object { "{0,-20} {1}" -f $_.n, $_.u }
Write-Host ""
Write-Host "Try a scenario:  .\scripts\demo.ps1 failed-logins     Stop:  .\scripts\stop-local.ps1"
if (-not $ok) { exit 1 }
