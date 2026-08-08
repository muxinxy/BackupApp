#!/bin/sh
# BackupApp generated backup script (plan: {{PLAN}})
# 多源备份。zip 支持密码；tar.gz 不支持密码；7z 需要 7z 命令（否则回退 tar.gz）。
set -e
APP="{{APP}}"
DEST="{{DEST}}"
TS=$(date +%Y%m%d_%H%M%S)
PW={{PW}}
mkdir -p "$DEST"
if [ "{{COMPRESS}}" = "1" ]; then
    if [ "{{FMT}}" = "zip" ]; then
        if [ -n "$PW" ]; then
            zip -rqP "$PW" "$DEST/${APP}_${TS}.zip" {{SRC_PATHS}}
        else
            zip -rq "$DEST/${APP}_${TS}.zip" {{SRC_PATHS}}
        fi
    elif [ "{{FMT}}" = "7z" ] && command -v 7z >/dev/null 2>&1; then
        7z a "$DEST/${APP}_${TS}.7z" {{SRC_PATHS}} >/dev/null
    elif [ "{{FMT}}" = "7z" ]; then
        echo "warning: 7z 格式需要 7z 命令，回退为 tar.gz" >&2
        tar -czf "$DEST/${APP}_${TS}.tar.gz" {{ARCHIVE_ARGS}}
    else
        tar -czf "$DEST/${APP}_${TS}.tar.gz" {{ARCHIVE_ARGS}}
    fi
else
    mkdir -p "$DEST/${APP}_${TS}"
    cp -a {{SRC_PATHS}} "$DEST/${APP}_${TS}"
fi
echo "backup done: $DEST/${APP}_${TS}"
