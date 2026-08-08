# BackupApp generated restore script (plan: {{PLAN}})
# Restores the newest snapshot. Existing source is renamed to <name>.<ts>.old
$ErrorActionPreference = "Stop"
$App  = "{{APP}}"
$Src  = "{{SRC}}"
$Dest = "{{DEST}}"
$Backup = Get-ChildItem -Path $Dest -Filter "$($App)_*" -ErrorAction SilentlyContinue |
    Sort-Object Name -Descending | Select-Object -First 1
if (-not $Backup) { Write-Error "no backup found in $Dest"; exit 1 }
if (Test-Path $Src) {
    Rename-Item $Src "$(Split-Path $Src -Leaf).$(Get-Date -Format 'yyyyMMdd_HHmmss').old"
}
New-Item -ItemType Directory -Path $Src -Force | Out-Null
if ("{{COMPRESS}}" -eq "1") {
    Expand-Archive -Path $Backup.FullName -DestinationPath $Src -Force
} else {
    Copy-Item -Path (Join-Path $Backup.FullName "*") -Destination $Src -Recurse -Force
}
Write-Host "restored from $($Backup.Name)"
