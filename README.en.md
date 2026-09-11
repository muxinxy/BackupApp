# BackupApp

> This is the English version of README.md. The Chinese version is the authoritative source.

A portable, cross-platform backup tool for application configs and data. It provides a PySide6 desktop GUI and a CLI for backing up app configs and data to a local directory or remote storage, with support for compression, encryption, scheduled tasks and retention policies.

## Features

- **Backup / restore**: `copy` / `link` modes (link mode can replace the source path with a junction/symlink pointing at the backup directory), incremental retention supported
- **Command hooks**: each backup plan can run "pre-backup / post-backup" commands or scripts (e.g. stop/start services) with a configurable timeout; a failing pre-hook aborts the backup, a failing post-hook only logs
- **Multi-protocol targets**: local directory, FTP, SFTP, S3, WebDAV
- **Compression and encryption**: zip (AES) / 7z / tar.gz, optional archive password
- **Retention policies**: keep the most recent N backups or those within N days, plus optional monthly/yearly first snapshot
- **Scheduled tasks**: both a global task (back up all) and per-plan tasks (back up a specific plan) can register/cancel system scheduled tasks, with batch register/cancel and live status views; frequencies: daily / weekly / every N days / every N hours / every N minutes / at logon (per-plan custom or follow the global setting)
- **Script generation**: generate standalone all-in-one backup/restore scripts (bat / ps1 / sh) that run without this tool; support interactive and argument-driven silent runs, with the same retention policy as the GUI (copies/days + monthly/yearly first):
  - `script.ps1` → interactively choose the operation
  - `script.ps1 backup -y` → silent backup
  - `script.ps1 restore -y [-Snapshot name] [-NoPrebak]` → silent restore (backs up the current config first by default, snapshot selectable)
- **Credential security**: DPAPI (Windows native encryption) / keyring (cross-platform OS credential store) / plain, three storage options
- **Self backup / restore**: back up the tool's own config (`apps/` + `settings.json`) to remote storage (FTP/SFTP/S3/WebDAV), with per-protocol configs saved independently; the GUI can view the remote backup file list (name/size/time) and supports **restoring** or **deleting** a single backup; before restoring, current data is automatically moved to a `data/self_restore_old_*` safety net
- **Remote gateway compatibility**: WebDAV works with OpenList and similar gateways (standard `{DAV:}` namespace, href URL decoding, GET 302 signed-address following); S3 list/download works through CDN/OSS gateways (boto3 + presigned URL)
- **Import / export**: export the entire config as a zip and re-import it for migration. Export supports optional AES encryption; import can choose whether to overwrite apps with the same ID and whether to restore global settings (self-backup config/theme etc.); encrypted zips require a password
- **Multilingual**: Simplified Chinese / English UI (GUI and CLI); language switchable from the toolbar or auto-detected from the OS; documentation (README / DEVELOPMENT / CHANGELOG) available in English

## Installation

### Scoop (Windows, recommended)

```bash
scoop bucket add mxy https://github.com/muxinxy/scoop-bucket
scoop install mxy/backupapp
```

After installation, a **BackupApp** shortcut (GUI) appears in the Start menu; the command line provides `backupapp` (i.e. `backupapp-cli.exe`). Config and data are stored in `backupapp\data`, which is set to persist, so `scoop update` upgrades don't lose them. Registered scheduled tasks point at the `current` link and remain valid after upgrades.

### Run from source

Requires Python >= 3.11.

```bash
pip install -e .
```

## Usage

```bash
# Launch the desktop GUI
backupapp gui

# Back up all apps
backupapp backup --all

# Back up a specific plan
backupapp backup --plan vscode/cfg

# Restore
backupapp restore --app vscode [--snapshot 20260808_103000]

# Scheduled task switch
backupapp task on|off|status

# Generate a standalone backup/restore all-in-one script (includes backup and restore, supports interactive and -y silent)
backupapp script --app vscode --plan cfg --flavor ps1

# Export / import config
backupapp export --all -o out.zip
backupapp import out.zip

# Validate config and data directories
backupapp validate

# Self backup (all enabled protocols by default, single one selectable with --protocol)
backupapp self-backup [--protocol webdav|s3|ftp|sftp]

# List remote self-backup files (name/size/backup time)
backupapp self-list --protocol webdav

# Restore a specific self backup from remote (overwrites apps/ + settings.json, old data moved to .old first)
backupapp self-restore --protocol webdav --file backupapp_MyPC_20260815_023740.zip

# Delete a remote self-backup file
backupapp self-delete --protocol webdav --file backupapp_MyPC_20260815_023740.zip
```

## Packaging

The PyInstaller spec lives at `packaging/backupapp.spec`:

```bash
pyinstaller packaging/backupapp.spec
```

## Directory Structure

```
backupapp/
  engine/      backup, restore, compression, retention policies, links and path handling
  protocols/   remote protocol adapters (FTP / SFTP / S3 / WebDAV) + self-backup orchestration (runner)
  storage/     config storage, import/export, file locks
  security.py  credential encryption (plain / dpapi / keyring)
  gui/         PySide6 desktop UI (main window / dialogs / background workers / themes)
  scripts/     standalone backup/restore script generation (bat / ps1 / sh templates)
scripts/        development smoke-test scripts
tests/          tests and fixtures
packaging/      PyInstaller packaging config and icons
```

## Development

```bash
python scripts/smoke_test.py      # core logic smoke test
python scripts/protocol_smoke.py  # protocol + self backup/restore smoke test
python scripts/gui_smoke.py       # GUI smoke test
python scripts/security_smoke.py  # credential encryption smoke test
```

Handover and release workflow: see [DEVELOPMENT.en.md](DEVELOPMENT.en.md).
