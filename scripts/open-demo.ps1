<#
  Open the collector's egress proof panel and the dashboard side by side (task E22), ready to present.

    .\scripts\open-demo.ps1
    .\scripts\open-demo.ps1 -Dashboard http://127.0.0.1:5173 -Panel http://127.0.0.1:8101/local/ui

  Uses Microsoft Edge in app mode, each window on half of the screen. If Edge is not found the two pages open in
  your default browser instead.
#>
param(
  [string]$Dashboard = "http://127.0.0.1:5173",
  [string]$Panel = "http://127.0.0.1:8101/local/ui"
)
Add-Type -AssemblyName System.Windows.Forms
$area = [System.Windows.Forms.Screen]::PrimaryScreen.WorkingArea
$half = [int]($area.Width / 2)
$edge = (Get-Command msedge.exe -ErrorAction SilentlyContinue).Source
if (-not $edge) { $edge = (Get-ChildItem "C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe", "C:\Program Files\Microsoft\Edge\Application\msedge.exe" -ErrorAction SilentlyContinue | Select-Object -First 1).FullName }
if ($edge) {
  $profile = Join-Path $env:TEMP "signal-labs-demo-profile"  # a separate profile so the two windows do not merge into one
  Start-Process $edge -ArgumentList "--app=$Panel", "--user-data-dir=$profile-panel", "--window-position=$($area.X),$($area.Y)", "--window-size=$half,$($area.Height)"
  Start-Process $edge -ArgumentList "--app=$Dashboard", "--user-data-dir=$profile-dash", "--window-position=$($area.X + $half),$($area.Y)", "--window-size=$half,$($area.Height)"
  Write-Host "Opened the egress panel (left) and the dashboard (right)."
} else {
  Start-Process $Panel
  Start-Process $Dashboard
  Write-Host "Edge not found: opened both pages in the default browser."
}
