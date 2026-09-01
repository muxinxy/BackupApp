# Changelog

> This is the English version of CHANGELOG.md. The Chinese version is the authoritative source.
> Chinese version: [CHANGELOG.md](CHANGELOG.md)

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
