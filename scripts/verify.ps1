<#
  Proof tools (task E19): one command, PASS or FAIL.

    .\scripts\verify.ps1            # match verifier and canary scan
    .\scripts\verify.ps1 match      # the egress log equals what the SaaS stored
    .\scripts\verify.ps1 canary     # planted secrets appear nowhere on the platform

  Exit code 0 = PASS, 1 = FAIL, 2 = INCOMPLETE (a required check could not run).
  Needs the stack from run-local.ps1. The database scan needs psql (found automatically, or set $env:PG_BIN).
  Evidence is written to docs\p3\evidence\verify-<time>.md and .json.
#>
param([string]$What = "all")
$root = Split-Path -Parent $PSScriptRoot
$python = if ($env:PYTHON) { $env:PYTHON } else { "python" }
$envFile = Join-Path $root "data\run.env.json"
if (Test-Path $envFile) {
  $run = Get-Content $envFile -Raw | ConvertFrom-Json
  if ($run.saas_url) { $env:SAAS_URL = $run.saas_url }
  if ($run.ca) { $env:SAAS_CA_FILE = $run.ca }
}
& $python "$root\simulator\verify.py" $What @args
exit $LASTEXITCODE
