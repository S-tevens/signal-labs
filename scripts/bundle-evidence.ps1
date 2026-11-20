<#
  Evidence bundle (task E30): one zip with the run's evidence, the exact commit and the settings the numbers were
  measured with, ready to hand to a teammate or attach to the submission.

    .\scripts\bundle-evidence.ps1

  Writes data\evidence-bundle-<UTC time>.zip containing docs\p3\evidence (measurements, proof runs, traces,
  scenario checks, rehearsals), the demo guides, the thresholds and policy files, and a MANIFEST.txt with the commit,
  branch and collector timing. The bundle is refused if any file contains something that looks like a credential.
#>
$root = Split-Path -Parent $PSScriptRoot
Set-Location $root
$stamp = (Get-Date).ToUniversalTime().ToString("yyyyMMddTHHmmssZ")
$stage = Join-Path $env:TEMP "signal-labs-bundle-$stamp"
New-Item -ItemType Directory -Force $stage | Out-Null

$commit = (git rev-parse HEAD) 2>$null; $branch = (git rev-parse --abbrev-ref HEAD) 2>$null
$dirty = if ((git status --porcelain) 2>$null) { "yes (uncommitted changes present)" } else { "no" }
$timing = "collector not reachable"
try { $timing = (Invoke-RestMethod "http://127.0.0.1:8101/local/timing" -TimeoutSec 4 | ConvertTo-Json -Compress) } catch { }
@("Signal Labs evidence bundle", "UTC: $stamp", "Commit: $commit", "Branch: $branch", "Uncommitted changes: $dirty", "Collector timing in use: $timing", "",
  "Contents: evidence/ (docs/p3/evidence), guides/, config/ (thresholds.yaml, policy.yaml, mapping.yaml, health.yaml).",
  "Measurements are one run per row on one machine; see evidence/SUMMARY.md for how to read them.") | Set-Content (Join-Path $stage "MANIFEST.txt") -Encoding utf8

Copy-Item (Join-Path $root "docs\p3\evidence") (Join-Path $stage "evidence") -Recurse
New-Item -ItemType Directory -Force (Join-Path $stage "guides"), (Join-Path $stage "config") | Out-Null
foreach ($f in "docs\p3\collector.md", "docs\p4\demo-runbook.md", "docs\phase-3.md", "docs\phase-4.md") { if (Test-Path $f) { Copy-Item $f (Join-Path $stage "guides") } }
foreach ($f in "saas\config\thresholds.yaml", "collector\policy.yaml", "collector\mapping.yaml", "collector\health.yaml") { if (Test-Path $f) { Copy-Item $f (Join-Path $stage "config") } }

# Refuse to bundle anything that looks like a credential.
$pattern = 'dev-secret-[a-z]+|\bdash-[a-z]+\b|\bkey-[a-z]+-\d\b|Bearer\s+[A-Za-z0-9._-]{20,}|AKIA[0-9A-Z]{16}|enroll(ment)?[_-]token["'': =]+[A-Za-z0-9._-]{12,}'
$hits = Get-ChildItem $stage -Recurse -File | Select-String -Pattern $pattern -CaseSensitive:$false | Where-Object { $_.Line -notmatch 'AKIAABCDEFGHIJKLMNOP' } | Select-Object -First 10  # that one is the fake test key the secret scenario prints
if ($hits) {
  Write-Host "Refusing to bundle: these files look like they contain a credential:" -ForegroundColor Red
  $hits | ForEach-Object { Write-Host ("  {0}:{1}" -f $_.Path.Replace($stage, ""), $_.LineNumber) }
  Remove-Item $stage -Recurse -Force
  exit 1
}
$zip = Join-Path $root "data\evidence-bundle-$stamp.zip"
New-Item -ItemType Directory -Force (Split-Path $zip) | Out-Null
Compress-Archive -Path (Join-Path $stage "*") -DestinationPath $zip -Force
Remove-Item $stage -Recurse -Force
Write-Host ("Bundle: {0} ({1} KB), commit {2}" -f $zip, [math]::Round((Get-Item $zip).Length / 1KB), $commit.Substring(0, 8))
