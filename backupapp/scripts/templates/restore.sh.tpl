#!/bin/sh
# BackupApp generated restore script (plan: {{PLAN}})
# Restores the newest snapshot. Existing source is renamed to <name>.<ts>.old
set -e
APP="{{APP}}"
SRC="{{SRC}}"
DEST="{{DEST}}"
TS=$(date +%Y%m%d_%H%M%S)
ENTRY=$(ls -1d "$DEST"/${APP}_* 2>/dev/null | sort -r | head -n1)
[ -n "$ENTRY" ] || { echo "no backup found in $DEST"; exit 1; }
if [ -e "$SRC" ]; then mv "$SRC" "$SRC.$TS.old"; fi
if [ -f "$ENTRY" ]; then
    mkdir -p "$SRC"
    case "$ENTRY" in
        *.zip) (cd "$SRC" && unzip -q "$ENTRY") ;;
        *)     tar -xzf "$ENTRY" -C "$SRC" ;;
    esac
else
    cp -a "$ENTRY"/. "$SRC"
fi
echo "restored from $ENTRY"
