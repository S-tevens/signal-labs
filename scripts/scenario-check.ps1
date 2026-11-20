<#
  Scenario check (task E28): a normal baseline and the injected scenarios, with expected versus actual results and the
  false and missed alerts counted. About 2.5 minutes.

    .\scripts\scenario-check.ps1
    .\scripts\scenario-check.ps1 --warmup 40 --inject 15 --seed 3

  Needs the stack from run-local.ps1 (leave the simulator off for a clean count). Evidence goes to
  docs\p3\evidence\scenarios-<time>.md. Exit code 0 = all passed.
#>
$root = Split-Path -Parent $PSScriptRoot
$python = if ($env:PYTHON) { $env:PYTHON } else { "python" }
$envFile = Join-Path $root "data\run.env.json"
if (Test-Path $envFile) {
  $run = Get-Content $envFile -Raw | ConvertFrom-Json
  if ($run.saas_url) { $env:SAAS_URL = $run.saas_url }
  if ($run.ca) { $env:SAAS_CA_FILE = $run.ca }
}
& $python "$root\simulator\scenario_check.py" @args
exit $LASTEXITCODE
