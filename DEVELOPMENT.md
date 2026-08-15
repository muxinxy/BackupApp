# DEVELOPMENT.md — 开发交接文档

面向接手开发者的项目全貌：架构、关键设计决策、测试与发布流程。

## 1. 技术栈

| 项 | 选择 | 说明 |
|---|---|---|
| 语言 | Python >= 3.11 | 类型标注贯穿全项目 |
| GUI | PySide6 >= 6.6 | Qt for Python，Fusion + QSS 主题 |
| 打包 | PyInstaller（onedir 双 exe） | spec 见 `packaging/backupapp.spec` |
| 依赖 | 见 `pyproject.toml` | boto3（S3）、httpx（WebDAV）、paramiko（SFTP）、pyzipper/py7zr（压缩）、keyring（凭据库）、platformdirs |

## 2. 架构总览

```
backupapp/
  __main__.py        CLI 入口（argparse 子命令分发，无子命令时启动 GUI）
  model.py           数据模型：AppConfig / BackupPlan / Settings + schema 迁移
  security.py        凭据加密：plain / dpapi(ctypes) / keyring
  scheduler.py       系统计划任务（Windows 任务计划程序）注册/取消/状态
  logging.py         日志（滚动文件）
  engine/            备份引擎
    backup.py        执行备份（copy/link 模式、增量保留）
    restore.py       应用级恢复
    compress.py      压缩格式注册表：zip(AES) / 7z / tar.gz / 目录拷贝
    retention.py     保留策略（份/天 + 月/年快照）+ 本地条目剪枝
    link.py          junction/symlink 链接处理
    paths.py         路径展开（~、环境变量）
  protocols/         远程协议 + 自身备份编排
    base.py          Uploader 抽象接口 + RemoteFile(name,size,mtime) + prune_remote
    webdav.py        WebDAV（httpx）
    s3.py            S3（boto3，presigned URL 下载）
    ftp.py / sftp.py FTP / SFTP
    runner.py        自身备份编排：run_self_backup / run_self_restore / list_remote_files / delete_remote_file
  storage/           数据存储
    store.py         应用 JSON / 全局设置读写（data 根目录可 --data-dir 覆盖）
    importexport.py  配置导出/导入 zip
    lock.py          文件锁（防 GUI 与计划任务并发）
  gui/               PySide6 界面
    app.py           应用入口
    main_window.py   主窗口（工具栏分组、应用列表、计划表格、日志、调度器）
    app_dialog.py / plan_dialog.py  应用/计划编辑对话框
    settings_dialogs.py  自身备份设置对话框 + 自身备份文件管理对话框（列表/恢复/删除）+ 调度器控件
    workers.py       QThread 后台 worker（备份/恢复/测试/自身备份列表/恢复/删除）
    theme.py         明/暗主题 + 状态色
packaging/backupapp.spec   PyInstaller 配置（双 exe + 数据收集）
scripts/            冒烟测试（见第 5 节）
```

## 3. 关键设计决策（交接必读）

### 3.1 数据模型与 schema 迁移
- JSON 字段驼峰（`selfBackup`），代码内 snake_case（`self_backup`）。
- `model.SCHEMA_VERSION = 2`，迁移函数注册在 `MIGRATIONS[v]`（v 版 → v+1 版），`from_dict` 自动链式迁移。
- v2 变更：`selfBackup` 单对象 → `selfBackups` dict（key=协议名），每协议独立配置。

### 3.2 自身备份的多协议独立配置
- `settings.json → selfBackups: {webdav: {...}, s3: {...}, ...}`，每个协议各自的 host/bucket/凭据/保留策略。
- **单协议启用**：GUI 保存时若勾选启用，其他协议一律 `enabled=False`（`settings_dialogs.SelfBackupDialog._save`）。
- `Settings.enabled_sbs()` 返回启用协议列表；`run_self_backup(protocol=None)` 默认跑所有启用协议。

### 3.3 远程备份命名与保留
- 文件名 `backupapp_<设备名>_<YYYYMMDD_HHMMSS>.<ext>`（设备名 = 本机 hostname 清洗，`protocols/base.device_name`）。
- `SNAP_RE` 正则匹配该格式；远程/本地剪枝按文件名排序即按时间排序。
- 本地副本在 `data/backups/`，`engine/retention.prune(dest, "backupapp", ...)` 走特殊分支匹配设备名格式。

### 3.4 远程协议兼容性（踩坑记录）
- **WebDAV 命名空间**：OpenList 等网关返回大写 `<D:>` 前缀 = 标准 `{DAV:}` 命名空间，用 `{DAV:}href` 解析（曾误用小写 `{dav:}` 导致列表恒空）。
- **href URL 解码**：`unquote()` 处理 `%20` 等编码。
- **WebDAV 下载 302**：文件 GET 302 到 OSS 签名地址时，`httpx` 需 `follow_redirects=True`；跨域重定向 httpx 自动剥 Authorization、不带 Referer → 绕过 OSS 防盗链 403。
- **S3 下载 403**：boto3 `download_file` 先发 HeadObject 被网关 403；改用 `generate_presigned_url` + httpx GET 302 跟随。
- **S3 SigV4 query**：`list_objects_v2` 带 query 时签名规范要求 query 独立一行（boto3 已正确处理，手写签名曾踩坑）。
- **S3 请求头**：GET/DELETE 不带 Content-Type（否则 web 端 fetch 触发 CORS preflight），boto3 已正确处理。

### 3.5 自身备份恢复
- `run_self_restore(protocol, remote_name)`：下载 → 解压 → `_find_self_root` 定位归档根（兼容三种结构：顶层 apps/、`data/` 根、v1 随机子目录）→ 旧数据移到 `data/self_restore_old_<ts>/` → 覆盖恢复。
- **空 apps 归档**：未配置任何应用时 `create_archive` 不写 apps 条目，恢复端以 settings.json 为锚点、apps 缺失视为空（兜底创建）。
- GUI 恢复/删除完成后发 `restored` 信号，主窗口 `_on_self_restored` 刷新应用列表（否则要重启才看到）。

### 3.6 凭据存储
| 方式 | 存储 | 安全 | 注意 |
|---|---|---|---|
| plain | settings.json 明文 | 低 | 便携场景 |
| dpapi | base64(DPAPI(明文)) | 高 | 绑定当前 Windows 用户，换机/换用户无法解密 |
| keyring | OS 凭据库 | 高 | key 按协议区分：`selfbackup_remote_<protocol>` / `selfbackup_archive_<protocol>` |

### 3.7 计划任务
- Windows 任务计划程序；全局任务 `backup --all`，计划级任务指向具体计划。
- 任务名按 `backupapp_<app>_<plan>` 生成，GUI 用缓存查询避免每行起子进程。

### 3.8 GUI 线程模型
- 所有 I/O（备份/恢复/测试/远程列表）走 `gui/workers.py` 的 QThread，不冻结界面。
- worker 内统一 `lock.DataLock` 防与计划任务并发。

### 3.9 导入导出（storage/importexport.py）
- `export_all(out, password)`：全部应用 + settings.json 打 zip；password 非空时 AES 加密（pyzipper）。
- `import_(path, overwrite, password, import_settings)`：
  - `overwrite=False` 跳过已存在的同 ID 应用；
  - `import_settings=True` 恢复 zip 内 settings.json 的自身备份配置（按协议合并，不覆盖本地其他协议）；
  - 加密 zip 需 password。
- GUI 导出/导入均有选项弹窗（加密开关+密码 / 覆盖+恢复设置+密码）。

### 3.10 自身备份恢复的覆盖策略
- `run_self_restore(protocol, name, overwrite=True)`：`overwrite=False` 时仅恢复本机不存在的应用（同 ID 保留现有），settings.json 照常恢复。
- GUI 恢复确认弹窗三选：覆盖（推荐）/ 仅新增 / 取消；CLI `self-restore --no-overwrite`。

### 3.11 FTP 网关兼容（踩坑记录）
- **TLS 自动降级**：GUI 默认勾选"使用 SSL/TLS"，但部分 FTP 网关不支持 TLS（550 TLS config）——`_connect()` 先试 FTP_TLS，失败自动降级普通 FTP。
- **PASV 偶发超时重试**：网关的被动数据连接偶发建立慢（>10s timeout），上传/下载用 `_retry`（最多 3 次，TimeoutError 时重连重试）。
- **TYPE I**：`retrbinary` 不自动设二进制模式，ASCII 下部分服务器 RETR 卡死/报 550——下载前显式 `voidcmd("TYPE I")`。
- **绝对路径**：远程路径统一绝对路径操作，避免相对 cwd 叠加导致 550 CD issue。
- **SFTP 流式传输**：部分 SFTP 网关不支持 paramiko `put()`/`get()`（连接被断开），改用 `open().write()/read()` 流式。

### 3.12 自身备份设置超时与启用
- 各协议有独立 `timeout`（默认 10s，GUI 可调 1-600s），接入 WebDAV/S3/FTP/SFTP。
- GUI 打开时默认选中已启用协议；未勾选"启用"保存时询问是否启用。
- 自身备份默认压缩（`compress=True`，GUI 默认勾选）。

## 4. 数据目录

- 默认 `platformdirs.user_data_dir("BackupApp")`；`--data-dir` 可覆盖（便携模式 = exe 同目录 `data/`）。
- 结构：`apps/*.json`（应用配置）、`settings.json`（全局）、`logs/`、`backups/`（本地副本）、`self_restore_old_*/`（恢复安全网）。

## 5. 测试

| 命令 | 覆盖 |
|---|---|
| `python scripts/smoke_test.py` | 核心逻辑：压缩往返、保留策略、链接、路径 |
| `python scripts/protocol_smoke.py` | 协议 + 自身备份全链路（WebDAV stub：大写 D: 命名空间、href 编码、元数据、恢复、删除、多协议隔离、CLI 接线） |
| `python scripts/gui_smoke.py` | GUI offscreen 渲染 + 经主窗口触发真实备份 worker |
| `python scripts/security_smoke.py` | 凭据加密往返 + 脚本生成（注：`generate()` 4 参调用为 baseline 遗留问题，与本次改动无关） |

所有冒烟脚本自包含（自建临时数据目录），可重复运行。

## 6. 打包与发布

### 6.1 构建 exe
```bash
scripts\build.ps1          # 一键构建（用 python -m PyInstaller，勿用 .venv 里的 pyinstaller.exe 入口）
# 产物：dist\backupapp\backupapp.exe（GUI）+ backupapp-cli.exe（CLI）
```

### 6.2 发布新版本（发布者执行）
1. 升版本号：`pyproject.toml` + `backupapp/__init__.py` + `backupapp.json`（scoop manifest 的 version/url）
2. 更新 README 功能清单与 changelog
3. 构建 exe（上一步）
4. 打 zip：`dist\backupapp-windows-x64.zip`（压缩 `dist\backupapp\` 内容，zip 内直接是 `backupapp\...`）
5. 提交并推送（含 tag `v<版本>`）
6. GitHub Release：标题 `v<版本>`，正文贴 changelog，附件传 zip（scoop `autoupdate` 按 `releases/download/v$version/backupapp-windows-x64.zip` 拉取）

## 7. 常见坑

- PyInstaller 需显式 hiddenimports（引擎/协议/GUI 惰性导入），boto3 全家桶用 `collect_all`。
- 窗口化构建下 stdout/stderr 为 None，`__main__.main` 开头重定向到 devnull。
- Windows 控制台默认 cp1252，输出中文前 `reconfigure(encoding="utf-8")`。
- QFormLayout 行显隐（`setRowVisible`）后窗口不自动收缩，需 `adjustSize()`。
- WebDAV PROPFIND 响应解析用 `{DAV:}` 前缀；服务器可能返回 207 多状态。
