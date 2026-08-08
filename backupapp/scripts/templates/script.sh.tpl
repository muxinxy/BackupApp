#!/bin/sh
# BackupApp generated script (plan: {{PLAN}})
# 备份 + 恢复一体。用法:
#   script.sh                交互式（选择 备份/恢复）
#   script.sh backup [-y]                    备份（-y 跳过确认）
#   script.sh restore [-y] [--snapshot 名称] [--no-prebak]
#     恢复。默认先备份当前配置/数据；--no-prebak 跳过。
#     --snapshot 指定备份名称（不指定则列出供选择）
set -e
APP="{{APP}}"
DEST="{{DEST}}"
FMT="{{FMT}}"
COMPRESS="{{COMPRESS}}"
KEEP={{KEEP}}
MONTHLY={{MONTHLY}}
PW={{PW}}
SRC="{{SRC}}"

do_backup() {
    TS=$(date +%Y%m%d_%H%M%S)
    mkdir -p "$DEST"
    if [ "$COMPRESS" = "1" ]; then
        if [ "$FMT" = "zip" ]; then
            OUT="$DEST/${APP}_${TS}.zip"
            rm -f "$OUT"
            ZIP="zip -rq"
            [ -n "$PW" ] && ZIP="zip -rqP $PW"
            {{ZIP_CMDS}}
        elif [ "$FMT" = "7z" ] && command -v 7z >/dev/null 2>&1; then
            7z a "$DEST/${APP}_${TS}.7z" {{SRC_PATHS}} >/dev/null
        elif [ "$FMT" = "7z" ]; then
            echo "warning: 7z 格式需要 7z 命令，回退到 tar.gz" >&2
            tar -czf "$DEST/${APP}_${TS}.tar.gz" {{ARCHIVE_ARGS}}
        else
            tar -czf "$DEST/${APP}_${TS}.tar.gz" {{ARCHIVE_ARGS}}
        fi
    else
        mkdir -p "$DEST/${APP}_${TS}"
        cp -a {{SRC_PATHS}} "$DEST/${APP}_${TS}"
    fi
    if [ "$KEEP" -gt 0 ]; then
        ENTRIES=$(ls -1d "$DEST"/${APP}_* 2>/dev/null | sort -r)
        COUNT=0
        SEEN_MONTHS=""
        for E in $ENTRIES; do
            COUNT=$((COUNT+1))
            SNAP=$(basename "$E" | sed 's/\([0-9]\{8\}_[0-9]\{6\}\).*/\1/')
            MONTH=${SNAP%_*}
            if [ "$COUNT" -le "$KEEP" ]; then
                SEEN_MONTHS="$SEEN_MONTHS $MONTH"
                continue
            fi
            if [ "$MONTHLY" != "1" ]; then
                rm -rf "$E"
                continue
            fi
            case " $SEEN_MONTHS " in
                *" $MONTH "*) rm -rf "$E" ;;
                *) SEEN_MONTHS="$SEEN_MONTHS $MONTH" ;;
            esac
        done
    fi
    echo "backup done: $DEST/${APP}_${TS}"
}

list_snapshots() {
    ls -1d "$DEST"/${APP}_* 2>/dev/null | sed 's/.*\///' | sort -r
}

do_restore() {
    SNAP="$1"
    PREBAK="$2"
    if [ "$PREBAK" = "1" ]; then
        echo "== 先备份当前配置/数据 =="
        do_backup
    fi
    if [ -z "$SNAP" ]; then
        AVAIL=$(list_snapshots)
        if [ -z "$AVAIL" ]; then
            echo "no backup found in $DEST" >&2
            exit 1
        fi
        echo "可用备份:"
        i=1
        for E in $AVAIL; do echo "  $i) $E"; i=$((i+1)); done
        printf "选择编号 (默认 1): "
        read -r SEL
        [ -z "$SEL" ] && SEL=1
        SNAP=$(echo "$AVAIL" | sed -n "${SEL}p")
        [ -z "$SNAP" ] && { echo "无效选择" >&2; exit 1; }
    fi
    ENTRY="$DEST/$SNAP"
    [ -e "$ENTRY" ] || ENTRY=$(ls -1d "$DEST"/${SNAP}* 2>/dev/null | head -n1)
    [ -n "$ENTRY" ] && [ -e "$ENTRY" ] || { echo "backup not found: $SNAP" >&2; exit 1; }
    TS=$(date +%Y%m%d_%H%M%S)
    if [ -e "$SRC" ]; then mv "$SRC" "$SRC.$TS.old"; fi
    mkdir -p "$SRC"
    if [ -f "$ENTRY" ]; then
        case "$ENTRY" in
            *.zip) (cd "$SRC" && unzip -q "$ENTRY") ;;
            *.7z)  7z x "$ENTRY" -o"$SRC" >/dev/null ;;
            *)     tar -xzf "$ENTRY" -C "$SRC" ;;
        esac
    else
        cp -a "$ENTRY"/. "$SRC"
    fi
    # 归档以单个根目录形态保存时解开一层（与 GUI 恢复行为一致）
    if [ "$(ls -A "$SRC" | wc -l)" = "1" ]; then
        D=$(ls -A "$SRC")
        if [ -d "$SRC/$D" ]; then
            (cd "$SRC/$D" && cp -a . "$SRC"/) && rm -rf "$SRC/$D"
        fi
    fi
    echo "restored from $SNAP"
}

ACTION=""
SNAP=""
PREBAK=1
ASSUME=0
for A in "$@"; do
    case "$A" in
        backup|restore) ACTION="$A" ;;
        -y|--yes) ASSUME=1 ;;
        --no-prebak) PREBAK=0 ;;
        --snapshot) ;;
        --snapshot=*) SNAP="${A#--snapshot=}" ;;
        *) [ -z "$SNAP" ] && SNAP="$A" ;;
    esac
done

if [ -z "$ACTION" ]; then
    printf "选择操作 [b=备份, r=恢复]: "
    read -r ANS
    case "$ANS" in
        b|B|backup) ACTION=backup ;;
        r|R|restore) ACTION=restore ;;
        *) echo "无效选择" >&2; exit 1 ;;
    esac
fi

if [ "$ACTION" = "backup" ]; then
    if [ "$ASSUME" = "0" ]; then
        printf "开始备份？[Y/n]: "
        read -r ANS
        case "$ANS" in n|N) exit 0 ;; esac
    fi
    do_backup
elif [ "$ACTION" = "restore" ]; then
    if [ "$ASSUME" = "0" ] && [ "$PREBAK" = "1" ]; then
        printf "恢复前先备份当前配置/数据？[Y/n]: "
        read -r ANS
        case "$ANS" in n|N) PREBAK=0 ;; esac
    fi
    do_restore "$SNAP" "$PREBAK"
else
    echo "unknown action: $ACTION" >&2
    exit 1
fi
