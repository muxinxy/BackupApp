# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller spec：backupapp（onedir，保证启动速度，产物打 zip/tar.gz）。

双 EXE：
- backupapp.exe      窗口化（无控制台）：双击/快捷方式入口，GUI 默认；CLI 子命令
                     同样可用（stdout 走 devnull，退出码正确），供计划任务调用
- backupapp-cli.exe  控制台版：终端里跑 CLI 看输出用

要点：
- templates 必须随包（生成脚本功能）
- 引擎/协议/GUI 均为惰性导入（CLI 按子命令 import），需显式 hiddenimports
- boto3/botocore 含服务模型数据，collect_all 全量收集
"""

import os
import sys

from PyInstaller.utils.hooks import collect_all

ROOT = os.path.abspath(os.path.join(SPECPATH, ".."))

icon = None
if sys.platform == "win32":
    icon = os.path.join(ROOT, "packaging", "icons", "backupapp.ico")

datas = [(os.path.join(ROOT, "backupapp", "scripts", "templates"),
          os.path.join("backupapp", "scripts", "templates")),
         (os.path.join(ROOT, "backupapp", "gui", "icons"),
          os.path.join("backupapp", "gui", "icons"))]
binaries = []
hiddenimports = [
    "backupapp.engine.backup",
    "backupapp.engine.restore",
    "backupapp.protocols.runner",
    "backupapp.scripts.generator",
    "backupapp.gui.app",
    "pyzipper",
    "py7zr",
]

for _pkg in ("boto3", "botocore", "py7zr", "pyzipper"):
    _d, _b, _h = collect_all(_pkg)
    datas += _d
    binaries += _b
    hiddenimports += _h

a = Analysis(
    [os.path.join(ROOT, "packaging", "entry.py")],
    pathex=[ROOT],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
)

pyz = PYZ(a.pure)

exe_gui = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="backupapp",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
    disable_windowed_traceback=False,
    icon=icon,
)

exe_cli = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="backupapp-cli",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=True,
    icon=icon,
)

coll = COLLECT(
    exe_gui,
    exe_cli,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=False,
    name="backupapp",
)
