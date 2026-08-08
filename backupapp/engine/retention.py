"""备份条目（快照）命名与保留策略。

条目命名：<app_id>_<YYYYMMDD_HHMMSS>[.zip|.7z|.tar.gz]
保留策略：最近 N 份（或 N 天内）+（可选）每月第一份 +（可选）每年第一份。
"""

import os
import re
import shutil
from datetime import datetime

ENTRY_RE = re.compile(
    r"^(?P<app>[\w.-]+)_(?P<snap>\d{8}_\d{6})(\.(?P<ext>zip|7z|tar\.gz))?$"
)


def entry_path(dest: str, app_id: str, snapshot: str, compress: bool,
               fmt: str | None = None) -> str:
    name = f"{app_id}_{snapshot}"
    if compress:
        name += f".{fmt}"
    return os.path.join(dest, name)


def list_entries(dest: str, app_id: str) -> list[str]:
    """该应用在 dest 下的备份条目，按快照从新到旧排序。"""
    if not os.path.isdir(dest):
        return []
    out = []
    for name in os.listdir(dest):
        m = ENTRY_RE.match(name)
        if m and m.group("app") == app_id:
            out.append(os.path.join(dest, name))
    out.sort(key=os.path.basename, reverse=True)
    return out


def snapshot_of(entry_path_: str) -> str:
    m = ENTRY_RE.match(os.path.basename(entry_path_))
    return m.group("snap") if m else ""


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
