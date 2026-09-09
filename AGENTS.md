# AGENTS.md — BackupApp

跨平台应用配置/数据备份工具（Python >= 3.11 + PySide6 GUI）。**接手前先读 [DEVELOPMENT.md](DEVELOPMENT.md)（英文版 [DEVELOPMENT.en.md](DEVELOPMENT.en.md)）**——它包含完整架构图、关键设计决策和踩坑记录，本文件只列最常踩的点。

## Shell 环境（重要）

- 本机已通过 scoop 安装 PowerShell 7（`pwsh`）。运行 shell 命令/脚本时**优先用 `pwsh`，不要用 cmd 或系统自带的 Windows PowerShell 5**。
- 构建脚本 `scripts\build.ps1` 用 `pwsh scripts\build.ps1` 运行。

## 常用命令

```powershell
.venv\Scripts\python.exe scripts\smoke_test.py        # 核心逻辑：压缩往返、保留策略、链接、路径
.venv\Scripts\python.exe scripts\protocol_smoke.py    # 协议 + 自身备份全链路（WebDAV stub）
.venv\Scripts\python.exe scripts\gui_smoke.py         # GUI offscreen 渲染 + 真实备份 worker
.venv\Scripts\python.exe scripts\security_smoke.py    # 凭据加密往返
.venv\Scripts\python.exe scripts\i18n_check.py check  # i18n 完整性检查（改 GUI 文案后必跑）
pwsh scripts\build.ps1                                # PyInstaller 构建 dist\backupapp（GUI + CLI 双 exe）
```

所有冒烟脚本自包含（自建临时数据目录），可重复运行。无独立 lint/typecheck 配置。

## 架构边界

- `backupapp/model.py` — 数据模型 + schema 迁移。JSON 字段驼峰（`selfBackup`），代码内 snake_case；加字段须注册 `MIGRATIONS[v]` 迁移函数（当前 `SCHEMA_VERSION = 2`）。
- `backupapp/engine/` — 备份引擎（备份/恢复/压缩注册表/保留策略/链接/路径展开），不依赖 GUI。
- `backupapp/protocols/` — 远程协议（webdav/s3/ftp/sftp）+ 自身备份编排 `runner.py`；`base.py` 定义 `Uploader` 抽象接口与远程文件剪枝。
- `backupapp/storage/` — JSON 存储、导入导出、文件锁。数据目录默认 `platformdirs.user_data_dir("BackupApp")`，`--data-dir` 可覆盖。
- `backupapp/gui/` — PySide6。**所有 I/O 必须走 `gui/workers.py` 的 QThread worker**，并在 worker 内用 `storage/lock.py` 的 `DataLock` 防与计划任务并发，不得在主线程做网络/磁盘大操作。
- `backupapp/i18n.py` + `backupapp/locales/en.py` — 轻量 i18n（gettext 风格 `_()`，中文源串 + 英文目录）。

## i18n 规则（强制）

- 所有面向用户的字符串（含日志消息）必须包在 `_("...")` 里；禁止 `_(f"...")`。
- 每个 key 必须出现在 `backupapp/locales/en.py` 的 `MESSAGES`；`{placeholder}` 集合须与译文一致；`_()` 外不得出现裸中文字符串字面量。
- 改完跑 `python scripts/i18n_check.py check`（AST 级检查，见脚本头部 A–E 五项）。
- GUI 切语言后自动重启（v1.1.1 行为），新 UI 控件需支持运行时翻译。

## 已知坑（详见 DEVELOPMENT.md §3.4/§3.11/§7）

- `schtasks /query /fo csv /v` 冷查询可达数秒（本机实测 ~3.9s）。**GUI 线程禁止同步调 `scheduler` 查询**——注册状态一律走 `gui/workers.py` 的 `SchedRefreshWorker`（单飞，结果喂 `MainWindow._registered_plans` 与 `SchedulerGroup.set_state`）。
- `schtasks` 输出按系统 ANSI 码页（中文系统 GBK）：`scheduler._run` 已显式 `encoding="mbcs"`，别改成默认 utf-8。
- 主题是 QSS + QPalette 双层：改色板同步动 `theme._build_palette`，否则未命中 QSS 的普通 QWidget（滚动区视口/表单容器）在暗黑主题下会退回浅色 Fusion 调色板变白。
- WebDAV PROPFIND 解析用大写 `{DAV:}` 命名空间；下载需 `follow_redirects=True`（302 到签名地址）。
- S3 下载走 `generate_presigned_url` + httpx GET（boto3 `download_file` 的 HeadObject 会被网关 403）。
- FTP：下载前显式 `voidcmd("TYPE I")`；TLS 失败自动降级；PASV 超时用 `_retry`。SFTP 用 `open().write()/read()` 流式而非 `put()/get()`。
- 远程备份文件名格式 `backupapp_<设备名>_<YYYYMMDD_HHMMSS>.<ext>`，`SNAP_RE` 靠它剪枝，勿改。
- 自身备份单协议启用：GUI 保存时启用某协议会把其他协议 `enabled=False`。
- PyInstaller 需显式 hiddenimports；构建用 `python -m PyInstaller`（.venv 的 `pyinstaller.exe` 入口会静默失败）。
- 窗口化 exe 的 stdout 为 None（`__main__` 已重定向）；Windows 控制台输出中文前需 `reconfigure(encoding="utf-8")`。
- `gui/widgets.py` 的 `WheelLock` 事件过滤器必须持有引用（如 `self._wheel_locks`），否则被 GC 后失效。

## 发版

升版本号改 `pyproject.toml` + `backupapp/__init__.py` 两处；CI（`.github/workflows/build.yml`）出 5 个产物：`windows-x64` / `macos-x64`（Intel runner `macos-15-intel`）/ `macos-arm64` / `linux-x64` / `linux-arm64`，tag 推送时自动传 Release。scoop manifest 在外部仓库 `muxinxy/scoop-bucket` 维护（只覆盖 Windows x64，发版后同步 version/url/hash）。详见 DEVELOPMENT.md §6。
