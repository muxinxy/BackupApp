# BackupApp

应用配置与数据备份工具（便携，跨平台）。提供 PySide6 桌面 GUI 与 CLI，备份应用配置与数据到本地目录或远程存储，支持压缩加密、计划任务与保留策略。

## 功能

- **备份 / 恢复**：copy / link 两种模式（link 模式可将源路径替换为指向备份目录的 junction/symlink），支持增量保留
- **多协议目标**：本地目录、FTP、SFTP、S3、WebDAV
- **压缩与加密**：zip（AES）/ 7z / tar.gz，可选压缩包密码
- **保留策略**：保留最近 N 份或 N 天内的备份 + 可选每月/每年第一份快照
- **计划任务**：全局任务（备份全部）与单个计划任务（备份指定计划）均可注册/取消系统计划任务，支持批量注册/取消与实时状态查看；频率支持每天 / 每周 / 每 N 天 / 每 N 小时 / 每 N 分钟 / 登录时（计划可自定义或跟随全局）
- **脚本生成**：生成独立的备份/恢复一体脚本（bat / ps1 / sh），不依赖本工具即可执行，支持交互式与参数静默运行，保留策略与 GUI 一致（份/天 + 每月/每年第一份）：
  - `script.ps1` → 交互式选择操作
  - `script.ps1 backup -y` → 静默备份
  - `script.ps1 restore -y [-Snapshot 名称] [-NoPrebak]` → 静默恢复（默认先备份当前配置，可指定快照）
- **凭据安全**：DPAPI（Windows 原生加密）/ keyring（跨平台 OS 凭据库）/ plain 三种存储方式
- **导入 / 导出**：配置整体导出为 zip 并可重新导入迁移

## 安装

### Scoop（Windows，推荐）

```bash
scoop bucket add mxy https://github.com/muxinxy/scoop-bucket
scoop install mxy/backupapp
```

安装后开始菜单出现 **BackupApp** 快捷方式（GUI），命令行可用 `backupapp`（即 `backupapp-cli.exe`）。配置与数据保存在 `backupapp\data`，已配置 persist，`scoop update` 升级不丢失。

### 源码运行

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

# 生成独立备份/恢复一体脚本（含备份与恢复，支持交互与 -y 静默）
backupapp script --app vscode --plan cfg --flavor ps1

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
