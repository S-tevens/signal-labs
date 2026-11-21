<#
  Run the customer side (collector + simulator) on this machine and send its metadata to the platform on Render.

    .\scripts\push-to-cloud.ps1 -Url https://signal-labs.onrender.com -Key <COLLECTOR_KEY> -Secret <COLLECTOR_SECRET>
    .\scripts\push-to-cloud.ps1 -Stop

  Key and Secret are the COLLECTOR_KEY and COLLECTOR_SECRET values in the Render service's Environment tab.
  Raw data stays here; the platform receives only the allow-listed metadata. Set $env:PYTHON if the default python lacks the packages.
#>
param([string]$Url, [string]$Key, [string]$Secret, [switch]$Stop)
$root = Split-Path -Parent $PSScriptRoot
Set-Location $root
$data = Join-Path $root "data"; $logs = Join-Path $data "logs"; $pidFile = Join-Path $data "cloud.pids"
New-Item -ItemType Directory -Force $logs | Out-Null
if (Test-Path $pidFile) { Get-Content $pidFile | ForEach-Object { Stop-Process -Id ([int]$_) -Force -ErrorAction SilentlyContinue }; Remove-Item $pidFile }
if ($Stop) { Write-Host "Stopped."; exit 0 }
if (-not ($Url -and $Key -and $Secret)) { Write-Host "Usage: -Url <https://...onrender.com> -Key <COLLECTOR_KEY> -Secret <COLLECTOR_SECRET>" -ForegroundColor Red; exit 1 }
$python = if ($env:PYTHON) { $env:PYTHON } else { "python" }
$env:SAAS_URL = $Url.TrimEnd("/"); $env:COLLECTOR_KEY = $Key; $env:COLLECTOR_SECRET = $Secret
$env:REGION = "in"; $env:TENANT_REF = "t-acme"; $env:PROFILE = "realtime"; $env:HEARTBEAT_INTERVAL_S = "5"
$env:DATA_DIR = Join-Path $data "collector-cloud"
Remove-Item $env:DATA_DIR -Recurse -Force -ErrorAction SilentlyContinue
$c = Start-Process $python -ArgumentList "-m", "uvicorn", "collector.main:app", "--port", "8101" -RedirectStandardOutput "$logs\cloud-collector.log" -RedirectStandardError "$logs\cloud-collector.err.log" -WindowStyle Hidden -PassThru
Start-Sleep -Seconds 6
$s = Start-Process $python -ArgumentList "simulator\generator.py", "--seconds", "86400" -RedirectStandardOutput "$logs\cloud-sim.log" -RedirectStandardError "$logs\cloud-sim.err.log" -WindowStyle Hidden -PassThru
@($c.Id, $s.Id) | Set-Content $pidFile
Write-Host "Collector (http://127.0.0.1:8101/local) and simulator are sending to $($env:SAAS_URL). Stop with: .\scripts\push-to-cloud.ps1 -Stop"
