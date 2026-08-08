# 一键构建 dist（修改代码后运行）。
# 注意：本机 .venv\Scripts\pyinstaller.exe 入口会静默失败，必须用 python -m PyInstaller。
$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
Set-Location $root

& ".venv\Scripts\python.exe" -m PyInstaller --noconfirm packaging\backupapp.spec
if ($LASTEXITCODE -ne 0) {
    Write-Host "build failed" -ForegroundColor Red
    exit $LASTEXITCODE
}
Write-Host "dist 已生成: $root\dist\backupapp" -ForegroundColor Green
