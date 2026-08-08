# BackupApp generated script (plan: {{PLAN}})
# 备份 + 恢复一体。用法:
#   script.ps1                 交互式（选择 备份/恢复）
#   script.ps1 backup -Yes                    备份（-Yes 跳过确认）
#   script.ps1 restore -Yes [-NoPrebak] [-Snapshot 名称]
#     恢复。默认先备份当前配置/数据；-NoPrebak 跳过。
#     -Snapshot 指定备份名称（不指定则列出供选择）
param(
    [Parameter(Position = 0)][string]$Action = "",
    [switch]$Yes,
    [string]$Snapshot = "",
    [switch]$NoPrebak
)
$ErrorActionPreference = "Stop"
$App  = "{{APP}}"
$Dest = "{{DEST}}"
$Fmt  = "{{FMT}}"
$Compress = "{{COMPRESS}}"
$Keep = [int]{{KEEP}}
$Monthly = "{{MONTHLY}}"
$Yearly = "{{YEARLY}}"
$Unit = "{{RETENTION_UNIT}}"
$Src  = "{{SRC}}"
$Srcs = @(
{{SRCS_PS}}
)

function Backup-BackupApp {
    $Ts = Get-Date -Format "yyyyMMdd_HHmmss"
    if (-not (Test-Path $Dest)) { New-Item -ItemType Directory -Path $Dest -Force | Out-Null }
    if ($Compress -eq "1") {
        $Out = Join-Path $Dest "$($App)_$($Ts).$Fmt"
        Compress-Archive -Path $Srcs -DestinationPath $Out -Force
    } else {
        $Dir = Join-Path $Dest "$($App)_$($Ts)"
        New-Item -ItemType Directory -Path $Dir -Force | Out-Null
        Copy-Item -Path $Srcs -Destination $Dir -Recurse -Force
    }
    # 保留策略：最近 KEEP 份 / KEEP 天内 + 每月/每年第一份
    if ($Keep -gt 0) {
        $SeenM = @()
        $SeenY = @()
        $i = 0
        $Now = Get-Date
        foreach ($E in (Get-ChildItem -Path $Dest -Filter "$($App)_*" | Sort-Object Name -Descending)) {
            $Snap = [regex]::Match($E.Name, '\d{8}_\d{6}').Value
            $M = $Snap.Substring(0, 6)
            $Y = $Snap.Substring(0, 4)
            if ($Unit -eq "days") {
                $In = ((($Now - [datetime]::ParseExact($Snap, 'yyyyMMdd_HHmmss', $null)).Days) -le $Keep)
            } else {
                $i++
                $In = ($i -le $Keep)
            }
            if ($In) { $SeenM += $M; $SeenY += $Y; continue }
            if ($Monthly -eq "1" -and $SeenM -notcontains $M) { $SeenM += $M; $SeenY += $Y; continue }
            if ($Yearly -eq "1" -and $SeenY -notcontains $Y) { $SeenM += $M; $SeenY += $Y; continue }
            Remove-Item $E.FullName -Recurse -Force
        }
    }
    Write-Host "backup done: $(Join-Path $Dest "$($App)_$($Ts)")"
}

function Get-Snapshots {
    Get-ChildItem -Path $Dest -Filter "$($App)_*" -ErrorAction SilentlyContinue |
        Sort-Object Name -Descending | ForEach-Object { $_.Name }
}

function Restore-BackupApp([string]$Snap, [int]$Prebak) {
    if ($Prebak -eq 1) { Write-Host "== 先备份当前配置/数据 =="; Backup-BackupApp }
    if (-not $Snap) {
        $List = @(Get-Snapshots)
        if ($List.Count -eq 0) { Write-Error "no backup found in $Dest"; exit 1 }
        Write-Host "可用备份:"
        for ($i = 0; $i -lt $List.Count; $i++) { Write-Host "  $($i + 1)) $($List[$i])" }
        $Sel = Read-Host "选择编号 (默认 1)"
        if (-not $Sel) { $Sel = 1 }
        $Snap = $List[[int]$Sel - 1]
    }
    $Entry = Join-Path $Dest $Snap
    if (-not (Test-Path $Entry)) {
        # 允许省略扩展名：按前缀匹配（zip/7z/tar.gz）
        $Cand = Get-ChildItem -Path $Dest -Filter "$($Snap)*" -ErrorAction SilentlyContinue |
            Sort-Object Name -Descending | Select-Object -First 1
        if ($Cand) { $Entry = $Cand.FullName }
    }
    if (-not (Test-Path $Entry)) { Write-Error "backup not found: $Snap"; exit 1 }
    if (Test-Path $Src) {
        Rename-Item $Src "$(Split-Path $Src -Leaf).$(Get-Date -Format 'yyyyMMdd_HHmmss').old"
    }
    New-Item -ItemType Directory -Path $Src -Force | Out-Null
    if ((Get-Item $Entry) -is [System.IO.DirectoryInfo]) {
        Copy-Item -Path (Join-Path $Entry "*") -Destination $Src -Recurse -Force
    } elseif ($Entry -like "*.zip") {
        Expand-Archive -Path $Entry -DestinationPath $Src -Force
    } else {
        # 7z / tar.gz：Win10+ 自带 bsdtar，支持解 7z/tar.gz
        tar -xf $Entry -C $Src
    }
    # 归档以单个根目录形态保存时解开一层（与 GUI 恢复行为一致）
    $Items = @(Get-ChildItem -Path $Src -Force -ErrorAction SilentlyContinue)
    if ($Items.Count -eq 1 -and $Items[0].PSIsContainer) {
        $Inner = $Items[0].FullName
        Get-ChildItem -Path $Inner -Force | Move-Item -Destination $Src -Force
        Remove-Item $Inner -Recurse -Force
    }
    Write-Host "restored from $Snap"
}

if (-not $Action) {
    $Ans = Read-Host "选择操作 [b=备份, r=恢复]"
    $Action = switch ($Ans.ToLower()) { "b" { "backup" } "r" { "restore" } default { "" } }
    if (-not $Action) { Write-Error "无效选择"; exit 1 }
}

switch ($Action.ToLower()) {
    "backup" {
        if (-not $Yes) {
            $Ans = Read-Host "开始备份？[Y/n]"
            if ($Ans.ToLower() -eq "n") { exit 0 }
        }
        Backup-BackupApp
    }
    "restore" {
        $Prebak = 1
        if ($NoPrebak) { $Prebak = 0 }
        if (-not $Yes -and $Prebak -eq 1) {
            $Ans = Read-Host "恢复前先备份当前配置/数据？[Y/n]"
            if ($Ans.ToLower() -eq "n") { $Prebak = 0 }
        }
        Restore-BackupApp $Snapshot $Prebak
    }
    default { Write-Error "unknown action: $Action"; exit 1 }
}
