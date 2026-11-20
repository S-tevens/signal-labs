<#
  Measure the real-time targets and delivery from timestamps (task E14).

    .\scripts\measure.ps1                 # everything, about 5 minutes
    .\scripts\measure.ps1 latency         # collection to dashboard, p95 <= 10 s
    .\scripts\measure.ps1 alert           # injected spike to alert, <= 15 s
    .\scripts\measure.ps1 offline         # collector killed to Poor, <= 60 s
    .\scripts\measure.ps1 delivery        # forced outage, sent vs received IDs

  Needs the stack from run-local.ps1 (use -Tls and -NoSimulator for the cleanest numbers).
  Writes an evidence file (.md and .json) to docs\p3\evidence. Extra arguments are passed through
  (--duration 90, --warmup 60, --outage 20).
#>
$root = Split-Path -Parent $PSScriptRoot
$python = if ($env:PYTHON) { $env:PYTHON } else { "python" }
$envFile = Join-Path $root "data\run.env.json"
if (Test-Path $envFile) {
  $run = Get-Content $envFile -Raw | ConvertFrom-Json
  if ($run.saas_url) { $env:SAAS_URL = $run.saas_url }
  if ($run.ca) { $env:SAAS_CA_FILE = $run.ca }
}
& $python "$root\simulator\measure.py" @args
exit $LASTEXITCODE
