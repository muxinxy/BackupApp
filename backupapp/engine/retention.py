"""备份条目（快照）命名与保留策略。

条目命名：<app_id>_<YYYYMMDD_HHMMSS>[.zip|.7z|.tar.gz]
保留策略：最近 N 份（或 N 天内）+（可选）每月第一份 +（可选）每年第一份。
"""

import os
import re
import shutil
from datetime import datetime, timedelta

ENTRY_RE = re.compile(
    r"^(?P<app>[\w.-]+)_(?P<snap>\d{8}_\d{6})(\.(?P<ext>zip|7z|tar\.gz))?$"
)

# 自身备份名 backupapp_<设备名>_<快照>.<ext>：设备名段可变，ENTRY_RE 匹配不到，
# 需要单独按时间戳定位。
_SELF_RE = re.compile(
    r"^backupapp[\w.-]*_\d{8}_\d{6}(\.(zip|7z|tar\.gz))?$"
)
_SNAP_TS_RE = re.compile(r"(\d{8}_\d{6})")


def snapshot_key(name: str) -> str:
    """排序键：取文件名中的快照时间戳（YYYYMMDD_HHMMSS）。

    备份名可能带设备名（backupapp_<设备>_<时间戳>），按整个文件名排序会先比
    设备名——多台设备共用一个远程目录时，这会把新备份排到旧备份后面，剪枝
    时误删最新的那份。统一按时间戳排序即可与设备名无关。
    解析不出时间戳时退回文件名本身，保证排序稳定且可比较。
    """
    base = os.path.basename(name)
    m = _SNAP_TS_RE.search(base)
    return m.group(1) if m else base


def entry_path(dest: str, app_id: str, snapshot: str, compress: bool,
               fmt: str | None = None) -> str:
    name = f"{app_id}_{snapshot}"
    if compress:
        name += f".{fmt}"
    return os.path.join(dest, name)


def unique_snapshot_from(used: set[str], snapshot: str) -> str:
    """在已用快照集合上避让，返回不冲突的快照名（保持 YYYYMMDD_HHMMSS 格式）。"""
    try:
        dt = datetime.strptime(snapshot, "%Y%m%d_%H%M%S")
    except ValueError:
        return snapshot  # 非标准快照名：不做处理，保持原样
    while dt.strftime("%Y%m%d_%H%M%S") in used:
        dt += timedelta(seconds=1)
    return dt.strftime("%Y%m%d_%H%M%S")


def list_entries(dest: str, app_id: str) -> list[str]:
    """该应用在 dest 下的备份条目，按快照从新到旧排序。

    app_id == "backupapp" 时匹配自身备份（backupapp_<device>_<snap>.<ext>，
    设备名段可缺省），与远程 SNAP_RE 规则一致。
    """
    if not os.path.isdir(dest):
        return []
    out = []
    if app_id == "backupapp":
        for name in os.listdir(dest):
            if _SELF_RE.match(name):
                out.append(os.path.join(dest, name))
    else:
        for name in os.listdir(dest):
            m = ENTRY_RE.match(name)
            if m and m.group("app") == app_id:
                out.append(os.path.join(dest, name))
    out.sort(key=snapshot_key, reverse=True)
    return out


def snapshot_of(entry_path_: str) -> str:
    """提取条目的快照时间戳。

    兼容自身备份名（backupapp_<设备>_<快照>.<ext>，ENTRY_RE 因设备名段匹配不上）。
    """
    base = os.path.basename(entry_path_)
    m = ENTRY_RE.match(base)
    if m:
        return m.group("snap")
    m = _SNAP_TS_RE.search(base)
    return m.group(1) if m else ""


def prune(dest: str, app_id: str, keep: int, keep_monthly: bool,
          keep_yearly: bool = False, unit: str = "count") -> int:
    """删除超出策略的旧条目，返回删除数量。keep<=0 时视为保留全部。

    unit="count" 保留最近 keep 份；unit="days" 保留最近 keep 天内的条目。
    超出窗口的条目中，每月/每年第一份（此前未见月份/年份）仍保留。
    """
    entries = list_entries(dest, app_id)
    if keep <= 0:
        return 0
    now = datetime.now()
    seen_months: set[str] = set()
    seen_years: set[str] = set()
    kept = 0
    for i, e in enumerate(entries):
        snap = snapshot_of(e)
        m, y = snap[:6], snap[:4]
        if unit == "days":
            try:
                age = (now - datetime.strptime(snap, "%Y%m%d_%H%M%S")).days
            except ValueError:
                age = 0
            in_window = age <= keep
        else:
            in_window = i < keep
        if in_window:
            kept += 1
        elif keep_monthly and m not in seen_months:
            kept += 1
        elif keep_yearly and y not in seen_years:
            kept += 1
        else:
            if os.path.isdir(e):
                shutil.rmtree(e, ignore_errors=True)
            else:
                try:
                    os.remove(e)
                except OSError:
                    pass
            continue
        seen_months.add(m)
        seen_years.add(y)
    return len(entries) - kept


def unique_snapshot(dest: str, app_id: str, snapshot: str,
                    fmt: str | None = None) -> str:
    """返回一个在该 dest 下不冲突的条目快照名。

    快照精确到秒，同一秒内连续两次备份会算出同一个条目名，后一份直接覆盖
    前一份（保留策略这时也只看到一份，等于静默丢备份）。冲突时逐秒前移。
    """
    used = {snapshot_of(e) for e in list_entries(dest, app_id)}
    used.discard("")
    return unique_snapshot_from(used, snapshot)
