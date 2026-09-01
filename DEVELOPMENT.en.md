# DEVELOPMENT.md — Development Handover Doc

> This is the English version of DEVELOPMENT.md. The Chinese version is the authoritative source.

A full picture of the project for incoming developers: architecture, key design decisions, testing and release workflow.

## 1. Tech Stack

| Item | Choice | Notes |
|---|---|---|
| Language | Python >= 3.11 | Type annotations throughout the project |
| GUI | PySide6 >= 6.6 | Qt for Python, Fusion + QSS theme |
| Packaging | PyInstaller (onedir, dual exe) | Spec in `packaging/backupapp.spec` |
| Dependencies | See `pyproject.toml` | boto3 (S3), httpx (WebDAV), paramiko (SFTP), pyzipper/py7zr (compression), keyring (credential store), platformdirs |

## 2. Architecture Overview

```
backupapp/
  __main__.py        CLI entry (argparse subcommand dispatch, starts GUI when no subcommand)
  model.py           Data models: AppConfig / BackupPlan / Settings + schema migration
  security.py        Credential encryption: plain / dpapi(ctypes) / keyring
  scheduler.py       System scheduled tasks (Windows Task Scheduler) register/cancel/status
  logging.py         Logging (rotating file)
  engine/            Backup engine
    backup.py        Runs backups (copy/link modes, incremental retention)
    restore.py       App-level restore
    compress.py      Compression format registry: zip(AES) / 7z / tar.gz / directory copy
    retention.py     Retention policy (count/day + monthly/yearly snapshots) + local entry pruning
    link.py          junction/symlink link handling
    paths.py         Path expansion (~, environment variables)
  protocols/         Remote protocols + self-backup orchestration
    base.py          Uploader abstract interface + RemoteFile(name,size,mtime) + prune_remote
    webdav.py        WebDAV (httpx)
    s3.py            S3 (boto3, presigned URL download)
    ftp.py / sftp.py FTP / SFTP
    runner.py        Self-backup orchestration: run_self_backup / run_self_restore / list_remote_files / delete_remote_file
  storage/           Data storage
    store.py         App JSON / global settings read-write (data root overridable with --data-dir)
    importexport.py  Config export/import zip
    lock.py          File lock (prevents GUI and scheduled task concurrency)
  gui/               PySide6 UI
    app.py           App entry
    main_window.py   Main window (toolbar groups, app list, plan table, log, scheduler)
    app_dialog.py / plan_dialog.py  App/plan edit dialogs
    settings_dialogs.py  Self-backup settings dialog + self-backup file manager dialog (list/restore/delete) + scheduler controls
    workers.py       QThread background workers (backup/restore/test/self-backup list/restore/delete)
    theme.py         Light/dark theme + status colors
packaging/backupapp.spec   PyInstaller config (dual exe + data collection)
scripts/             Smoke tests (see section 5)
```

## 3. Key Design Decisions (must-read for handover)

### 3.1 Data Model and Schema Migration
- JSON fields are camelCase (`selfBackup`), in-code identifiers are snake_case (`self_backup`).
- `model.SCHEMA_VERSION = 2`, migration functions registered in `MIGRATIONS[v]` (v → v+1), `from_dict` chains migrations automatically.
- v2 change: `selfBackup` single object → `selfBackups` dict (key = protocol name), each protocol has its own config.

### 3.2 Self-Backup Per-Protocol Independent Config
- `settings.json → selfBackups: {webdav: {...}, s3: {...}, ...}`, each protocol has its own host/bucket/credentials/retention policy.
- **Single protocol enabled**: when saving in the GUI with enable checked, all other protocols are forced to `enabled=False` (`settings_dialogs.SelfBackupDialog._save`).
- `Settings.enabled_sbs()` returns the list of enabled protocols; `run_self_backup(protocol=None)` runs all enabled protocols by default.

### 3.3 Remote Backup Naming and Retention
- Filename `backupapp_<device_name>_<YYYYMMDD_HHMMSS>.<ext>` (device name = sanitized local hostname, `protocols/base.device_name`).
- `SNAP_RE` regex matches this format; remote/local pruning sorts by filename, which is equivalent to sorting by time.
- Local copies live in `data/backups/`, `engine/retention.prune(dest, "backupapp", ...)` takes a special branch matching the device-name format.

### 3.4 Remote Protocol Compatibility (pitfall notes)
- **WebDAV namespace**: gateways like OpenList return the uppercase `<D:>` prefix = the standard `{DAV:}` namespace, parse with `{DAV:}href` (a lowercase `{dav:}` was once used by mistake, making the listing always empty).
- **href URL decoding**: `unquote()` handles encodings like `%20`.
- **WebDAV download 302**: when a file GET 302s to an OSS signed address, `httpx` needs `follow_redirects=True`; on cross-origin redirects httpx strips Authorization and sends no Referer → bypasses OSS hotlink-protection 403.
- **S3 download 403**: boto3 `download_file` sends a HeadObject first which the gateway rejects with 403; use `generate_presigned_url` + httpx GET following the 302 instead.
- **S3 SigV4 query**: when `list_objects_v2` carries a query, the signing spec requires the query on its own line (boto3 handles this correctly; hand-written signing hit this pitfall).
- **S3 request headers**: GET/DELETE carry no Content-Type (otherwise web-side fetch triggers a CORS preflight), boto3 already handles this.

### 3.5 Self-Backup Restore
- `run_self_restore(protocol, remote_name)`: download → extract → `_find_self_root` locates the archive root (compatible with three layouts: top-level apps/, `data/` root, v1 random subdirectory) → old data moved to `data/self_restore_old_<ts>/` → overwrite restore.
- **Empty apps archive**: when no app is configured, `create_archive` writes no apps entries; on the restore side settings.json is the anchor and a missing apps entry is treated as empty (created as a fallback).
- GUI emits the `restored` signal after restore/delete completes; the main window's `_on_self_restored` refreshes the app list (otherwise the change only shows after a restart).

### 3.6 Credential Storage
| Method | Storage | Security | Notes |
|---|---|---|---|
| plain | settings.json in plaintext | Low | For portable scenarios |
| dpapi | base64(DPAPI(plaintext)) | High | Bound to the current Windows user; cannot be decrypted on another machine or user |
| keyring | OS credential store | High | Keys are per-protocol: `selfbackup_remote_<protocol>` / `selfbackup_archive_<protocol>` |

### 3.7 Scheduled Tasks
- Windows Task Scheduler; a global task runs `backup --all`, plan-level tasks point at a specific plan.
- Task names are generated as `backupapp_<app>_<plan>`.
- **Query consolidation**: `status` / `plan_status` / `registered_plan_tasks` share a single cached `schtasks /query /v` (TTL 5 seconds, `_tasks_table`), columns located by header (Chinese/English headers, some systems have multiple hostname columns), avoiding spawning a subprocess on every GUI switch/refresh; subprocesses share a 20-second timeout.
- **scoop compatibility**: at frozen runtime `_stable_exe()` detects the `\apps\<app>\<version>\` layout and swaps the version directory for the `current` link (only if it exists), so tasks stay valid after upgrades; tasks registered with an old path show pathMismatch, clicking "Register" again updates them.

### 3.8 GUI Thread Model
- All I/O (backup/restore/test/remote listing) goes through QThreads in `gui/workers.py`, so the UI never freezes.
- Workers uniformly take `lock.DataLock` to prevent concurrent runs with scheduled tasks.

### 3.9 Import/Export (storage/importexport.py)
- `export_all(out, password)`: zips all apps + settings.json; AES-encrypted (pyzipper) when password is non-empty.
- `import_(path, overwrite, password, import_settings)`:
  - `overwrite=False` skips apps that already exist with the same ID;
  - `import_settings=True` restores the self-backup config from the zip's settings.json (merged per protocol, does not overwrite other local protocols);
  - Encrypted zips require the password.
- GUI export/import both show an options dialog (encryption toggle + password / overwrite + restore settings + password).

### 3.10 Self-Backup Restore Overwrite Policy
- `run_self_restore(protocol, name, overwrite=True)`: with `overwrite=False`, only apps that don't exist on this machine are restored (existing same-ID apps are kept), settings.json is always restored.
- The GUI restore confirmation dialog offers three choices: overwrite (recommended) / new-only / cancel; CLI uses `self-restore --no-overwrite`.

### 3.11 FTP Gateway Compatibility (pitfall notes)
- **TLS auto-downgrade**: the GUI checks "Use SSL/TLS" by default, but some FTP gateways don't support TLS (550 TLS config) — `_connect()` tries FTP_TLS first and automatically falls back to plain FTP on failure.
- **PASV intermittent timeout retry**: a gateway's passive data connection occasionally establishes slowly (>10s timeout); upload/download use `_retry` (up to 3 attempts, reconnecting and retrying on TimeoutError).
- **TYPE I**: `retrbinary` does not set binary mode automatically; under ASCII some servers hang or report 550 on RETR — explicitly `voidcmd("TYPE I")` before downloading.
- **Absolute paths**: remote paths always operate as absolute paths, avoiding stacked relative-cwd issues that cause 550 CD errors.
- **SFTP streaming**: some SFTP gateways don't support paramiko `put()`/`get()` (connection dropped), use `open().write()/read()` streaming instead.

### 3.12 Self-Backup Settings Timeout and Enable
- Each protocol has its own `timeout` (default 10s, GUI adjustable 1-600s), applies to WebDAV/S3/FTP/SFTP.
- When the GUI opens, the enabled protocol is selected by default; saving without "enable" checked asks whether to enable it.
- Self-backup compresses by default (`compress=True`, GUI checkbox checked by default).

### 3.13 Backup Plan Command Hooks (engine/hooks.py)
- `BackupPlan.pre_cmd` / `post_cmd` / `cmd_timeout` (JSON: `preCmd`/`postCmd`/`cmdTimeout`, default 60s).
- `run_hook(cmd, timeout, plan_key, when)`: executes via shell (Windows cmd / sh), raises `RuntimeError` on non-zero exit code or timeout.
- `backup.run_plan`: a failing pre-hook aborts the backup; a failing post-hook only logs a warning and does not affect the backup result.
- GUI plan dialog: pre-backup/post-backup command input fields + timeout (in seconds, manually enterable).

### 3.14 Spinbox Wheel Lock (gui/widgets.py WheelLock)
- Wheel events can accidentally change a QSpinBox value; the `WheelLock` event filter intercepts the wheel (forwarding it to the scroll area),
  preserving focus and manual input. **A reference must be held** (e.g. `self._wheel_locks`), otherwise interception stops working after GC.
- Applied to: retention count and command timeout in the plan dialog.

## 4. Data Directory

- Default is `platformdirs.user_data_dir("BackupApp")`; `--data-dir` overrides it (portable mode = `data/` next to the exe).
- Layout: `apps/*.json` (app configs), `settings.json` (global), `logs/`, `backups/` (local copies), `self_restore_old_*/` (restore safety net).

## 5. Testing

| Command | Coverage |
|---|---|
| `python scripts/smoke_test.py` | Core logic: compression round-trip, retention policy, links, paths |
| `python scripts/protocol_smoke.py` | Protocols + self-backup full chain (WebDAV stub: uppercase D: namespace, href encoding, metadata, restore, delete, multi-protocol isolation, CLI wiring) |
| `python scripts/gui_smoke.py` | GUI offscreen rendering + real backup worker triggered through the main window |
| `python scripts/security_smoke.py` | Credential encryption round-trip + script generation (note: the `generate()` 4-arg call is a baseline leftover, unrelated to this change) |

All smoke scripts are self-contained (they create their own temp data directory) and repeatable.

## 6. Packaging and Release

### 6.1 Building the exe
```bash
scripts\build.ps1          # One-click build (use python -m PyInstaller, not the pyinstaller.exe entry in .venv)
# Output: dist\backupapp\backupapp.exe (GUI) + backupapp-cli.exe (CLI)
```

### 6.2 Releasing a new version (maintainer action)
1. Bump the version: `pyproject.toml` + `backupapp/__init__.py` (the scoop manifest lives separately in the `muxinxy/scoop-bucket` repo; sync its version/url/hash after release)
2. Update the README feature list and changelog
3. Build the exe (previous step)
4. Make the zip: `dist\backupapp-windows-x64.zip` (compress the contents of `dist\backupapp\`, the zip directly contains `backupapp\...`)
5. Commit and push (with tag `v<version>`)
6. GitHub Release: title `v<version>`, body pastes the changelog, attach the zip (scoop `autoupdate` pulls from `releases/download/v$version/backupapp-windows-x64.zip`)

## 7. Common Pitfalls

- PyInstaller needs explicit hiddenimports (engine/protocol/GUI lazy imports); use `collect_all` for the boto3 family.
- In windowed builds stdout/stderr are None; `__main__.main` redirects them to devnull at the start.
- The Windows console defaults to cp1252; call `reconfigure(encoding="utf-8")` before outputting Chinese.
- QFormLayout rows that are shown/hidden (`setRowVisible`) don't auto-shrink the window; call `adjustSize()`.
- WebDAV PROPFIND response parsing uses the `{DAV:}` prefix; the server may return a 207 multi-status.
