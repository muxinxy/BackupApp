# BackupApp

应用配置与数据备份工具（便携，跨平台）。提供 PySide6 桌面 GUI 与 CLI，备份应用配置与数据到本地目录或远程存储，支持压缩加密、计划任务与保留策略。

## 功能

- **备份 / 恢复**：copy / link 两种模式（link 模式可将源路径替换为指向备份目录的 junction/symlink），支持增量保留
- **多协议目标**：本地目录、FTP、SFTP、S3、WebDAV
- **压缩与加密**：zip（AES）/ 7z / tar.gz，可选压缩包密码
- **保留策略**：按天数保留 + 每月快照保留
- **计划任务**：内置调度器，可开关、查看状态，也可生成独立的计划任务脚本
- **脚本生成**：一键生成独立的备份/恢复脚本（bat / ps1 / sh），不依赖本工具即可执行
- **凭据安全**：DPAPI（Windows 原生加密）/ keyring（跨平台 OS 凭据库）/ plain 三种存储方式
- **导入 / 导出**：配置整体导出为 zip 并可重新导入迁移

## 安装

要求 Python >= 3.11。

```bash
pip install -e .
```

## 使用

```bash
# 启动桌面 GUI
backupapp gui

# 备份全部应用
backupapp backup --all

# 备份指定计划
backupapp backup --plan vscode/cfg

# 恢复
backupapp restore --app vscode [--snapshot 20260808_103000]

# 计划任务开关
backupapp task on|off|status

# 生成独立备份脚本
backupapp script --app vscode --plan cfg --kind backup --flavor ps1

# 导出 / 导入配置
backupapp export --all -o out.zip
backupapp import out.zip

# 校验配置与数据目录
backupapp validate
```

## 打包

PyInstaller spec 位于 `packaging/backupapp.spec`：

```bash
pyinstaller packaging/backupapp.spec
```

## 目录结构

```
backupapp/
  engine/      备份、恢复、压缩、保留策略、链接与路径处理
  protocols/   协议适配器（FTP / SFTP / S3 / WebDAV / 本地）
  storage/     配置存储、导入导出、文件锁
  gui/         PySide6 桌面界面
  scripts/     独立备份/恢复脚本生成（bat / ps1 / sh 模板）
scripts/        开发用冒烟测试脚本
tests/          测试与夹具
packaging/      PyInstaller 打包配置与图标
```

## 开发

```bash
python scripts/smoke_test.py      # 核心逻辑冒烟
python scripts/protocol_smoke.py  # 协议冒烟
python scripts/gui_smoke.py       # GUI 冒烟
python scripts/security_smoke.py  # 凭据加密冒烟
```
