<#
  Dry-run a sample of the organizers' stream (task E26): what would the collector make of it, and what must be mapped?

    .\scripts\stream-check.ps1 sample.txt        # a file with a few dozen sample lines, any format
    Get-Content sample.txt | .\scripts\stream-check.ps1 -

  Nothing is sent or stored. Prints the format, host, metric and time found in each line, which sensitive patterns were
  seen, anything that did not map (with the lines to add to collector\mapping.yaml) and a verdict:
  READY (exit 0), NEEDS MAPPING (1) or NOTHING USABLE (2).
#>
$root = Split-Path -Parent $PSScriptRoot
$python = if ($env:PYTHON) { $env:PYTHON } else { "python" }
if ($args.Count -eq 0) { Write-Host "Usage: .\scripts\stream-check.ps1 <sample-file | ->"; exit 2 }
& $python "$root\simulator\stream_check.py" @args
exit $LASTEXITCODE
