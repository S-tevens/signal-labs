<#
  The addresses to give the organizers so they can push their stream to this collector.

    .\scripts\push-info.ps1               # addresses and examples; the token is shown as a placeholder
    .\scripts\push-info.ps1 -ShowToken    # also print the token (do this in front of the organizers only)

  Start the collector for pushing first:  .\scripts\run-local.ps1 -AcceptPush
  The token lives in data\ingest.token (git-ignored). The full interface description to hand over is
  docs\p3\push-interface.md. The first run may make Windows ask whether to allow Python through the firewall:
  allow it for the network you are on, or the organizers' machines will not be able to connect.
#>
param([switch]$ShowToken)
$root = Split-Path -Parent $PSScriptRoot
$tokenFile = Join-Path $root "data\ingest.token"
$token = if (Test-Path $tokenFile) { (Get-Content $tokenFile -Raw).Trim() } else { $null }
$ips = @(Get-NetIPAddress -AddressFamily IPv4 -ErrorAction SilentlyContinue | Where-Object { $_.IPAddress -notmatch '^(127\.|169\.254\.)' -and $_.PrefixOrigin -ne 'WellKnown' } | Select-Object -ExpandProperty IPAddress)
if (-not $ips) { $ips = @("<this machine's address>") }

$listening = $false
try { $null = Invoke-WebRequest "http://127.0.0.1:8101/healthz" -UseBasicParsing -TimeoutSec 3; $listening = $true } catch { }
if (-not $listening) { Write-Host "The collector is not running. Start it with: .\scripts\run-local.ps1 -AcceptPush" -ForegroundColor Red; exit 1 }
if (-not $token) { Write-Host "No ingest token yet: the collector was not started with -AcceptPush. Restart with: .\scripts\run-local.ps1 -Restart -AcceptPush" -ForegroundColor Red; exit 1 }
$shown = if ($ShowToken) { $token } else { "<token from data\ingest.token>" }

foreach ($ip in $ips) {
  Write-Host ""
  Write-Host "Push to this collector at $ip" -ForegroundColor Cyan
  Write-Host "  HTTP, any format (lines, JSON, a JSON array, NDJSON; gzip ok)   POST http://${ip}:8101/ingest"
  Write-Host "  InfluxDB line protocol (Telegraf influxdb output)              POST http://${ip}:8101/write"
  Write-Host "  OpenTelemetry metrics (OTLP/HTTP JSON)                         POST http://${ip}:8101/v1/metrics"
  Write-Host "  Syslog                                                         UDP ${ip}:5514   or   TCP ${ip}:5515 (one line per message)"
}
Write-Host ""
Write-Host "Authentication: send the token as  Authorization: Bearer <token>  (or X-Ingest-Token: <token>). Syslog over UDP/TCP carries no token: restrict who may send with INGEST_ALLOW." -ForegroundColor Yellow
Write-Host "Token: $shown"
Write-Host ""
Write-Host "Try it from the other machine:"
Write-Host ('  curl.exe -X POST http://{0}:8101/ingest -H "Authorization: Bearer {1}" -d "host=web-1 metric=cpu_pct value=42"' -f $ips[0], $shown)
Write-Host ""
Write-Host "The complete description to hand over: docs\p3\push-interface.md"
