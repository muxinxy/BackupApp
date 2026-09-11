# Changelog

> This is the English version of CHANGELOG.md. The Chinese version is the authoritative source.
> Chinese version: [CHANGELOG.md](CHANGELOG.md)

## v1.1.4 (2026-09-11)

This release focuses on a batch of fixes for data loss and silently dead features, plus faster remote backup/restore and UI refreshes.

**Data safety (important — upgrade recommended)**

- **Fixed retention sometimes deleting the newest backup**: backup filenames embed the device name (`backupapp_<device>_<timestamp>`), and sorting by the whole filename compares the device name first — when several machines share one remote folder, pruning could delete the newest snapshot while keeping other machines' older ones. Sorting now uses the snapshot timestamp
- **Fixed same-second backups overwriting each other**: snapshot names are second-precision, so two backups within the same second produced the same filename and the second silently overwrote the first (retention only saw one). Names now step forward second by second on collision, so both are kept
- **Fixed broken data after a failed restore**: on error the original data was left only inside the `.old` folder while the source path held a half-finished tree. A failed restore now rolls back, putting the original directory back; the temporary extraction directory is cleaned up on failure too
- **Fixed restore failing when the destination lives inside the source**: the archive was moved away together with the renamed source directory, so extraction reported "file not found". Extraction now happens before the source directory is touched, which also means a failure leaves the source untouched
- **Fixed self-including backups**: when the destination was inside a source, earlier backups were re-packed into each new one, growing it every run. The destination is now excluded automatically, with a log line
- **Fixed non-atomic config writes**: `settings.json` and app definitions were truncated and rewritten in place, so a crash or power loss left half a file and the app could not start. Writes now go through a temp file + `fsync` + atomic replace, and corrupt JSON is treated as "no data" with a log entry
- **Fixed failed backups counted as valid**: a half-written archive left behind by an interrupted compression landed under the normal filename, so retention counted it and it could be picked for restore. Archives are now written to `.part` and atomically renamed only on success
- **Fixed scheduled tasks running concurrently with manual backups**: the CLI (the entry point used by scheduled tasks) took no file lock and could write the same config files as a manual run. All backup/restore entry points are now locked

**Interface**

- **Fixed Import/Export doing nothing**: the option dialog's child widgets were destroyed early, so reading the options raised (silently swallowed by Qt). Import/export work again
- **Fixed task status always showing "Not registered" after registering**: the UI compared the plan ID, but the system task name is `BackupApp_<app>_<plan>` — never equal. Comparison now uses the task name
- **Fixed the global task always reporting "Path changed; re-apply required"**: `schtasks` drops the leading quote when reading a task command back, so the previous exact comparison never matched and falsely reported a path change. Comparison now tolerates quote/whitespace differences while still detecting real path changes
- **Fixed checkboxes being hard to see in dark mode**: the unchecked indicator border was nearly the same colour as the dark background. Indicators are now themed explicitly and a check-mark icon was added
- **Fixed the plan table not refreshing after clicking OK when editing a plan**: the table and task status stayed stale even though the edit was saved
- **Fixed the "Restore self backup" button doing nothing**
- **Fixed refreshes losing your place**: refreshes after a backup or task registration rebuilt the whole table, losing the selected row and scroll position. They are now incremental
- **Fixed a possible crash when closing the window**: closing during a backup destroyed a background thread that was still running
- **Fixed UI freezes when registering/cancelling scheduled tasks**: registration and cancellation now run in the background (previously only status queries did)
- **Fixed the self-backup file list**: switching protocols mid-request mixed up results, and restore/delete could be triggered repeatedly while one was running

**Performance**

- **Faster remote backup and restore**: HTTP connections are reused (each request used to re-handshake) and directory probes are cached (entering a directory used to re-query every level)
- **Large restores no longer fill memory**: remote downloads now stream to disk instead of reading the whole archive into RAM
- **Self backup packs once for multiple protocols**: with several protocols enabled the same data used to be re-packed per protocol; artifacts are now grouped by format and reused
- **Import/export no longer blocks the UI**
- **Faster log panel startup**: only the tail is read in chunks instead of loading the whole file

**Security**

- **Fixed path traversal in tar.gz extraction**: a malicious or tampered archive could write outside the destination (self-restore downloads an archive from a remote and extracts it). Out-of-bounds members are now rejected, and 7z members are validated too
- **Fixed FTP potentially sending credentials in cleartext**: any exception used to be treated as "server does not support TLS" and fall back to plaintext. The fallback now happens only on TLS negotiation failure; auth and network errors are reported as-is

**Other fixes**

- Hook timeouts now kill the whole process tree (previously only the shell died and child processes survived); oversized hook output no longer consumes large amounts of memory
- `.old` / `self_restore_old_*` safety-net directories are pruned to the 3 most recent, instead of growing without bound
- Fixed link mode misdetecting a real directory as a link (which risked deleting a real directory)
- Fixed the self-backup file count being reported one too high
- Added a timeout to `crontab` writes (Linux/macOS)
- The log level and max log size settings now actually take effect (they were ignored)
- The weekday dropdown no longer shows Chinese in the English UI
- Temporary files from self backup/restore are now cleaned up on failure too

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
