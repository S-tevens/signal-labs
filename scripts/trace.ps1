<#
  Trace one payload from the raw record to the incident (task E27).

    .\scripts\trace.ps1 --demo              # plant a test secret in a failed-login burst, then trace it
    .\scripts\trace.ps1 --latest            # the newest sent payload
    .\scripts\trace.ps1 <payload_id>        # a payload you picked in the egress panel

  Secrets are masked in the output. Exit code 0 = every hop passed. Evidence goes to docs\p3\evidence\trace-*.md.
#>
$root = Split-Path -Parent $PSScriptRoot
$python = if ($env:PYTHON) { $env:PYTHON } else { "python" }
$envFile = Join-Path $root "data\run.env.json"
if (Test-Path $envFile) {
  $run = Get-Content $envFile -Raw | ConvertFrom-Json
  if ($run.saas_url) { $env:SAAS_URL = $run.saas_url }
  if ($run.ca) { $env:SAAS_CA_FILE = $run.ca }
}
& $python "$root\simulator\trace.py" @args
exit $LASTEXITCODE
