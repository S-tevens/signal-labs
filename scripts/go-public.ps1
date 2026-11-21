<#
  Make the demo reachable on a public HTTPS address from this machine, for free and without an account.

    .\scripts\go-public.ps1            # restart the demo in hardened public mode, open a tunnel, print the address
    .\scripts\go-public.ps1 -Stop      # close the tunnel (the local demo keeps running)

  What it does: starts the stack with run-local.ps1 -Public (random collector secrets, no static API tokens, the built
  dashboard, collector traffic refused on the public address), then opens a tunnel to the dashboard port only. The
  collector, its egress panel and the platform ports stay on this machine.

  Tunnel: localhost.run over the SSH program that comes with Windows (no download, no account) first; if that fails, a
  Cloudflare quick tunnel (the program is downloaded once and its Cloudflare signature is checked). Some networks block
  one of them: this one blocks Cloudflare's quick-tunnel service.

  Judges sign in with organization t-acme and an account from data\dev-users.txt. The address works only while this machine
  is on and online, changes each time the tunnel starts, and the free service says it rotates domains periodically: check
  data\public-url.txt, and rerun this script for a fresh address if the old one stops working.
#>
param([switch]$Stop)
$root = Split-Path -Parent $PSScriptRoot
Set-Location $root
$logs = Join-Path $root "data\logs"
$pidFile = Join-Path $root "data\tunnel.pid"
New-Item -ItemType Directory -Force $logs | Out-Null

function Stop-Tunnel {
  if (Test-Path $pidFile) { Stop-Process -Id ([int](Get-Content $pidFile)) -Force -ErrorAction SilentlyContinue; Remove-Item $pidFile -Force }
  Get-Process cloudflared -ErrorAction SilentlyContinue | Stop-Process -Force
}
if ($Stop) { Stop-Tunnel; Write-Host "Tunnel closed."; exit 0 }

& (Join-Path $PSScriptRoot "reset-demo.ps1") -Public | Out-Null
Start-Sleep -Seconds 5
try { $null = Invoke-WebRequest "http://127.0.0.1:5173/api/healthz" -UseBasicParsing -TimeoutSec 8 } catch { Write-Host "The dashboard did not come up; see data\logs\dashboard.err.log" -ForegroundColor Red; exit 1 }
Stop-Tunnel

# 1. localhost.run over SSH (asks for JSON output, so the address is easy to read)
$out = Join-Path $logs "tunnel-ssh.log"; Remove-Item $out -ErrorAction SilentlyContinue
$p = Start-Process -FilePath ssh -ArgumentList "-T", "-o", "StrictHostKeyChecking=accept-new", "-o", "ServerAliveInterval=30", "-o", "ExitOnForwardFailure=yes", "-R", "80:127.0.0.1:5173", "nokey@localhost.run", "--", "--output", "json" -RedirectStandardOutput $out -RedirectStandardError "$out.err" -WindowStyle Hidden -PassThru
$url = $null
for ($i = 0; $i -lt 30 -and -not $url; $i++) {
  Start-Sleep -Seconds 1
  if (Test-Path $out) { $m = Select-String -Path $out -Pattern '"address":"([a-z0-9.-]+\.lhr\.life)"' | Select-Object -First 1; if ($m) { $url = "https://" + $m.Matches[0].Groups[1].Value } }
}
if ($url) { $p.Id | Set-Content $pidFile }
else { Stop-Process -Id $p.Id -Force -ErrorAction SilentlyContinue }

# 2. Cloudflare quick tunnel, if the first one did not work
if (-not $url) {
  Write-Host "localhost.run did not respond; trying a Cloudflare quick tunnel ..."
  $tool = Join-Path $root "data\tools\cloudflared"; $exe = Join-Path $tool "cloudflared.exe"
  if (-not (Test-Path $exe)) {
    New-Item -ItemType Directory -Force $tool | Out-Null
    Invoke-WebRequest "https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-windows-amd64.exe" -OutFile $exe -UseBasicParsing
    $sig = Get-AuthenticodeSignature $exe
    if ($sig.Status -ne "Valid" -or $sig.SignerCertificate.Subject -notmatch "Cloudflare") { Remove-Item $exe -Force; Write-Host "The download does not carry a valid Cloudflare signature; deleted." -ForegroundColor Red; exit 1 }
  }
  $log = Join-Path $logs "tunnel.log"; Remove-Item $log -ErrorAction SilentlyContinue
  $p = Start-Process -FilePath $exe -ArgumentList "tunnel", "--no-autoupdate", "--url", "http://127.0.0.1:5173" -RedirectStandardError $log -RedirectStandardOutput "$log.out" -WindowStyle Hidden -PassThru
  for ($i = 0; $i -lt 40 -and -not $url; $i++) {
    Start-Sleep -Seconds 1
    if (Test-Path $log) { $m = Select-String -Path $log -Pattern "https://[a-z0-9-]+\.trycloudflare\.com" | Where-Object { $_.Matches[0].Value -notmatch "//api\." } | Select-Object -First 1; if ($m) { $url = $m.Matches[0].Value } }
  }
  if ($url) { $p.Id | Set-Content $pidFile } else { Stop-Process -Id $p.Id -Force -ErrorAction SilentlyContinue }
}
if (-not $url) { Write-Host "No tunnel could be opened from this network; see data\logs. The local demo at http://127.0.0.1:5173 still works." -ForegroundColor Red; exit 1 }

$url | Set-Content (Join-Path $root "data\public-url.txt")
Write-Host ""
Write-Host "Live at: $url" -ForegroundColor Green
Write-Host "Sign in with organization t-acme and an account from data\dev-users.txt (admin, operator, viewer, auditor)."
Write-Host "Give the simulator about two minutes to build its baseline before showing the dashboard. Close the tunnel with: .\scripts\go-public.ps1 -Stop"
