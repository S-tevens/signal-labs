<#
  Rehearsal runner (task E22): every scenario and the proof checks in the order a judge would see them, with a pause
  between steps, ending in a pass/fail table with timestamps written to docs\p3\evidence\rehearsal-<time>.md.

    .\scripts\rehearse.ps1                    # about 8 minutes; 10 s between steps
    .\scripts\rehearse.ps1 -Pause 20          # longer pauses so incidents separate (correlation is per source and 120 s)
    .\scripts\rehearse.ps1 -WithMeasure       # also run the timing measurements (adds about 6 minutes)
    .\scripts\rehearse.ps1 -Only secret,hold  # just these steps

  Needs the stack from run-local.ps1 (use -Tls, leave the simulator on so the platform has a baseline).
  A step is FAIL if it exits non-zero or prints FAIL, MISMATCH or LEAK; otherwise it is PASS if it printed a verdict
  and "ran" if the scenario only shows you something to look at (the platform view or the panel).
#>
param(
  [int]$Pause = 10,
  [switch]$WithMeasure,
  [string[]]$Only = @()
)
$root = Split-Path -Parent $PSScriptRoot
$python = if ($env:PYTHON) { $env:PYTHON } else { "python" }
$envFile = Join-Path $root "data\run.env.json"
if (Test-Path $envFile) {
  $run = Get-Content $envFile -Raw | ConvertFrom-Json
  if ($run.saas_url) { $env:SAAS_URL = $run.saas_url }
  if ($run.ca) { $env:SAAS_CA_FILE = $run.ca }
}
$ErrorActionPreference = "Continue"

# Order: privacy first, then the live incidents, then reliability, then isolation, then proof.
$steps = @(
  @{ Name = "secret";        Cmd = @("simulator\scenarios.py", "secret") },
  @{ Name = "hold";          Cmd = @("simulator\scenarios.py", "hold") },
  @{ Name = "failed-logins"; Cmd = @("simulator\scenarios.py", "failed-logins") },
  @{ Name = "cpu-spike";     Cmd = @("simulator\scenarios.py", "cpu-spike") },
  @{ Name = "latency";       Cmd = @("simulator\scenarios.py", "latency") },
  @{ Name = "packet-loss";   Cmd = @("simulator\scenarios.py", "packet-loss") },
  @{ Name = "disk";          Cmd = @("simulator\scenarios.py", "disk") },
  @{ Name = "alert-storm";   Cmd = @("simulator\scenarios.py", "alert-storm") },
  @{ Name = "remediation";   Cmd = @("simulator\scenarios.py", "remediation") },
  @{ Name = "outage";        Cmd = @("simulator\scenarios.py", "outage") },
  @{ Name = "delivery";      Cmd = @("simulator\scenarios.py", "delivery") },
  @{ Name = "tenants";       Cmd = @("simulator\scenarios.py", "tenants") },
  @{ Name = "flood";         Cmd = @("simulator\scenarios.py", "flood") },
  @{ Name = "verify";        Cmd = @("simulator\verify.py", "all") }
)
if ($WithMeasure) { $steps += @{ Name = "measure"; Cmd = @("simulator\measure.py", "all") } }
if ($Only.Count) { $steps = @($steps | Where-Object { $Only -contains $_.Name }) }

# The collector must be reachable, or every step would fail for the same boring reason.
try { $null = Invoke-WebRequest -Uri "http://127.0.0.1:8101/healthz" -UseBasicParsing -TimeoutSec 5 }
catch { Write-Host "The collector is not running on 127.0.0.1:8101. Start the stack first: .\scripts\run-local.ps1 -Tls" -ForegroundColor Red; exit 2 }

$evidence = Join-Path $root "docs\p3\evidence"
New-Item -ItemType Directory -Force $evidence | Out-Null
$stamp = (Get-Date).ToUniversalTime().ToString("yyyyMMddTHHmmssZ")
$rows = @()
$logs = @()
$i = 0
foreach ($step in $steps) {
  $i++
  $start = (Get-Date).ToUniversalTime()
  Write-Host ""
  Write-Host ("[{0}/{1}] {2}" -f $i, $steps.Count, $step.Name) -ForegroundColor Cyan
  $lines = & $python (Join-Path $root $step.Cmd[0]) $step.Cmd[1..($step.Cmd.Count - 1)] 2>&1 | ForEach-Object { "$_" }
  $code = $LASTEXITCODE
  $lines | ForEach-Object { Write-Host "  $_" }
  $text = $lines -join "`n"
  $seconds = [math]::Round(((Get-Date).ToUniversalTime() - $start).TotalSeconds, 1)
  $hasVerdict = $text -cmatch "\bPASS\b"
  if ($code -ne 0 -or $text -cmatch "RESULT: FAIL|OVERALL: (FAIL|INCOMPLETE)|MISMATCH|\bLEAK\b|Traceback|\bFAIL\b|leaked into egress\? True") { $verdict = "FAIL" }
  elseif ($hasVerdict) { $verdict = "PASS" }
  else { $verdict = "ran" }
  Write-Host ("  => {0} ({1} s)" -f $verdict, $seconds) -ForegroundColor $(if ($verdict -eq "FAIL") { "Red" } else { "Green" })
  $rows += [pscustomobject]@{ Step = $step.Name; Started = $start.ToString("HH:mm:ss"); Seconds = $seconds; Verdict = $verdict }
  $logs += [pscustomobject]@{ Step = $step.Name; Text = $text }
  if ($i -lt $steps.Count -and $Pause -gt 0) { Write-Host "  pausing $Pause s ..."; Start-Sleep -Seconds $Pause }
}

$failed = @($rows | Where-Object { $_.Verdict -eq "FAIL" }).Count
$md = @("# Rehearsal run", "", "UTC start: $stamp. Pause between steps: $Pause s. Result: **" + $(if ($failed) { "$failed step(s) FAILED" } else { "no failures" }) + "**", "",
        "| Step | Started (UTC) | Seconds | Verdict |", "|---|---|---|---|")
$md += $rows | ForEach-Object { "| $($_.Step) | $($_.Started) | $($_.Seconds) | $($_.Verdict) |" }
$md += @("", "PASS = the step printed a verdict and no failure. ran = a scenario that shows you something to look at. FAIL = non-zero exit or a failure word in the output.", "", "## Output", "")
foreach ($l in $logs) { $md += @("### $($l.Step)", "", '```', $l.Text, '```', "") }
$file = Join-Path $evidence "rehearsal-$stamp.md"
$md | Set-Content -Path $file -Encoding utf8
Write-Host ""
$rows | Format-Table -AutoSize | Out-String | Write-Host
Write-Host "Evidence: $file"
exit $(if ($failed) { 1 } else { 0 })
