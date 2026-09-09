# Changelog

> This is the English version of CHANGELOG.md. The Chinese version is the authoritative source.
> Chinese version: [CHANGELOG.md](CHANGELOG.md)

## v1.1.3 (2026-09-09)

- **Fixed slow startup / plan editing**: scheduled-task registration status is now queried on a background thread (`schtasks /query` cold queries can take seconds and used to freeze the UI); buttons and table read a cache instead of blocking
- **Fixed white backgrounds in dark-theme dialogs**: light/dark themes now apply a QPalette consistent with the QSS; unstyled containers such as the plan dialog no longer fall back to the light palette
- **Pre/post backup hooks support script files**: type a command directly or click Browse to pick a script file — `.bat`/`.cmd`/`.ps1` on Windows (ps1 runs via PowerShell), `.sh` on macOS/Linux (runs via sh)
- **Fixed multiple unresponsive buttons**: Browse / Import / Export / Add File / Save Script dialogs were silently dead after the i18n refactor because the `_` variable shadowed the translation function; all fixed
- **Compatibility fix**: `schtasks` output is decoded with the system ANSI codepage (`mbcs`) so task-status queries no longer crash under a UTF-8 environment

## v1.1.2 (2026-09-06)

- **New architecture artifacts**: CI now builds 5 platform artifacts — Windows x64, macOS x64 / ARM64, Linux x64 / ARM64 (new native macOS ARM64 and Linux ARM64 builds)
- **Fixed macOS x64 artifact**: the previous `backupapp-macos-x64` was mistakenly built on Apple Silicon runners (actually an ARM64 binary); now uses the Intel runner `macos-15-intel` for a true x64 build
- macOS codesign/notarization now covers both macOS artifacts

## v1.1.1 (2026-09-02)

- **Auto-restart on language switch**: the app restarts automatically so the new language takes effect
- **Bilingual logs**: Chinese log fragments in the log panel and backup.log now follow the UI language (Simplified Chinese / English)

## v1.1.0 (2026-09-02)

- Added: bilingual support (Simplified Chinese / English) for the app UI, CLI, and documentation; English versions of README, DEVELOPMENT, and CHANGELOG.

## v1.0.5 (2026-08-24)

- **Live backup progress**: the log panel shows `Plan [processed/total] filename` (150ms throttling to prevent screen flicker)
- **Batch register/cancel scheduled tasks**: moved to background threads, no longer freezes the UI item by item
- **Navigation locked during backup**: app list / schedule table disabled to prevent accidental refreshes
- **Human-readable backup sizes**: `B/KB/MB/GB` format replaces raw byte counts (unified across GUI logs / CLI / log files)

## v1.0.4 (2026-08-23)

- **GUI performance optimization**: scheduled task status queries and the registered-task list are merged into a single cached query (5s TTL), and the `schtasks` subprocess now has a 20s timeout; the UI no longer freezes when switching apps or after a backup completes
- **Log panel**: auto-scrolls to the bottom when new logs are appended (including tail logs loaded at startup)
- **scoop upgrade compatibility**: when registering a scheduled task, the version directory (`apps\backupapp\1.0.4\...`) is automatically replaced with the `current` link, so scheduled tasks no longer break after `scoop update` (existing tasks need one more "Register" click in the UI)
- **Fix**: task parsing errors caused by schtasks Chinese headers / systems with multiple hostname columns

## v1.0.3

- Command hooks for backup plans (pre/post backup + timeout)
- Numeric field wheel locking (prevents accidental edits)

## v1.0.2

- Encryption and overwrite options for import/export
- FTP/SFTP gateway compatibility (TLS fallback, PASV retry, streaming)
- Restore overwrite policies (overwrite / add-only)

## v1.0.1

- Self backup/restore
- Independent configuration per protocol (WebDAV/S3/FTP/SFTP)
- Remote gateway compatibility (OpenList WebDAV, CDN/OSS S3)

## v1.0.0

- First stable release: backup/restore, compression & encryption, retention policies, scheduled tasks, script generation
