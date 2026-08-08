# BackupApp generated backup script (plan: {{PLAN}})
# 多源备份。PowerShell 压缩不支持密码（zip 加密请用应用本体执行）。
$ErrorActionPreference = "Stop"
$App  = "{{APP}}"
$Dest = "{{DEST}}"
$Srcs = @(
{{SRCS_PS}}
)
$Ts = Get-Date -Format "yyyyMMdd_HHmmss"
if (-not (Test-Path $Dest)) { New-Item -ItemType Directory -Path $Dest -Force | Out-Null }
if ("{{COMPRESS}}" -eq "1") {
    $Out = Join-Path $Dest "$($App)_$($Ts).{{FMT}}"
    Compress-Archive -Path $Srcs -DestinationPath $Out -Force
} else {
    $Dir = Join-Path $Dest "$($App)_$($Ts)"
    New-Item -ItemType Directory -Path $Dir -Force | Out-Null
    Copy-Item -Path $Srcs -Destination $Dir -Recurse -Force
}
Write-Host "backup done: $Dest\$($App)_$($Ts)"
