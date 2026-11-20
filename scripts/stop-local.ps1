<#
  Stop everything started by run-local.ps1.

    .\scripts\stop-local.ps1            # stop services and Postgres
    .\scripts\stop-local.ps1 -KeepDb    # stop services but leave Postgres running
#>
param([switch]$KeepDb)

$root = Split-Path -Parent $PSScriptRoot
$pidFile = Join-Path $root "data\run.pids.json"
$pgData = Join-Path $root "data\pg"

if (Test-Path $pidFile) {
  foreach ($s in (Get-Content $pidFile -Raw | ConvertFrom-Json)) {
    if (Get-Process -Id $s.pid -ErrorAction SilentlyContinue) {
      # /T also ends child processes (npm starts node); the process may already be gone, so ignore errors.
      & taskkill.exe /PID $s.pid /T /F 2>$null | Out-Null
      Write-Host "stopped $($s.name) (pid $($s.pid))"
    }
  }
  Remove-Item $pidFile -Force
} else {
  Write-Host "No saved process list; nothing to stop."
}

if (-not $KeepDb -and (Test-Path (Join-Path $pgData "PG_VERSION"))) {
  $pgBin = $env:PG_BIN
  if (-not $pgBin) {
    $f = Get-ChildItem "C:\Program Files\PostgreSQL\*\bin\pg_ctl.exe" -ErrorAction SilentlyContinue | Select-Object -First 1
    if ($f) { $pgBin = $f.Directory.FullName }
  }
  if ($pgBin) {
    Start-Process -FilePath (Join-Path $pgBin "pg_ctl.exe") -WindowStyle Hidden -Wait `
      -ArgumentList @("stop", "-D", "`"$pgData`"", "-m", "fast") 2>$null
    Write-Host "stopped Postgres"
  }
}
