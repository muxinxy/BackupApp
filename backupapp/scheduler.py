"""系统计划任务：只维护一个全局任务，开关即创建/删除。

win: schtasks / macOS: launchctl + LaunchAgents plist / linux: crontab。
Windows 分支为实测目标，mac/linux 为最佳努力实现。
"""

import os
import shlex
import subprocess
import sys

TASK_NAME = "BackupAppGlobalBackup"


def app_command(cfg) -> str:
    """全局备份命令：计划任务与文档中的入口，退出码反映成败。"""
    args = " ".join(cfg.scheduler.args) or "backup --all"
    if getattr(sys, "frozen", False):
        return f'"{sys.executable}" {args}'
    return f'"{sys.executable}" -m backupapp {args}'


def _run(cmd: list[str]) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, capture_output=True, text=True)


# ---- Windows ----

def _win_sc(cfg) -> list[str]:
    s = cfg.scheduler
    if s.frequency == "atLogon":
        return ["/sc", "onlogon"]
    if s.frequency == "weekly":
        return ["/sc", "weekly", "/st", s.time, "/d", str(s.day_of_week)]
    return ["/sc", "daily", "/st", s.time]


def _win_install(cfg) -> bool:
    cmd = ["schtasks", "/create", "/tn", TASK_NAME, "/tr", app_command(cfg),
           "/f"] + _win_sc(cfg)
    return _run(cmd).returncode == 0


def _win_uninstall() -> bool:
    return _run(["schtasks", "/delete", "/tn", TASK_NAME, "/f"]).returncode == 0


def _win_status(cfg) -> str:
    r = _run(["schtasks", "/query", "/tn", TASK_NAME, "/v", "/fo", "list"])
    if r.returncode != 0:
        return "missing"
    for line in r.stdout.splitlines():
        if "Task To Run" in line and app_command(cfg) not in line:
            return "pathMismatch"
    return "registered"


# ---- macOS ----

def _mac_plist(cfg) -> str:
    s = cfg.scheduler
    args = shlex.split(app_command(cfg))
    args_xml = "\n".join(f"    <string>{a}</string>" for a in args)
    if s.frequency == "atLogon":
        cal = "<key>RunAtLoad</key><true/>"
    else:
        hh, mm = (s.time or "02:30").split(":")
        cal = (f"<key>StartCalendarInterval</key><dict>"
               f"<key>Hour</key><integer>{int(hh)}</integer>"
               f"<key>Minute</key><integer>{int(mm)}</integer></dict>")
    return f"""<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
  <key>Label</key><string>{TASK_NAME}</string>
  <key>ProgramArguments</key><array>
{args_xml}
  </array>
  {cal}
</dict></plist>
"""


def _mac_plist_path() -> str:
    return os.path.expanduser(f"~/Library/LaunchAgents/{TASK_NAME}.plist")


def _mac_install(cfg) -> bool:
    p = _mac_plist_path()
    with open(p, "w", encoding="utf-8") as f:
        f.write(_mac_plist(cfg))
    r = _run(["launchctl", "load", "-w", p])
    return r.returncode == 0


def _mac_uninstall() -> bool:
    p = _mac_plist_path()
    _run(["launchctl", "unload", p])
    if os.path.exists(p):
        os.remove(p)
    return True


def _mac_status(cfg) -> str:
    r = _run(["launchctl", "list"])
    return "registered" if TASK_NAME in r.stdout else "missing"


# ---- Linux ----

def _cron_line(cfg) -> str:
    s = cfg.scheduler
    if s.frequency == "atLogon":
        return f"@reboot {app_command(cfg)} # {TASK_NAME}"
    hh, mm = (s.time or "02:30").split(":")
    if s.frequency == "weekly":
        day = s.day_of_week % 7  # 1=Mon..7=Sun -> cron 0=Sun..6=Sat
        return f"{mm} {hh} * * {day} {app_command(cfg)} # {TASK_NAME}"
    return f"{mm} {hh} * * * {app_command(cfg)} # {TASK_NAME}"


def _crontab_lines() -> list[str]:
    r = _run(["crontab", "-l"])
    return r.stdout.splitlines() if r.returncode == 0 else []


def _write_crontab(lines: list[str]) -> bool:
    r = subprocess.run(["crontab", "-"], input="\n".join(lines) + "\n",
                       capture_output=True, text=True)
    return r.returncode == 0


def _linux_install(cfg) -> bool:
    lines = [ln for ln in _crontab_lines() if TASK_NAME not in ln]
    lines.append(_cron_line(cfg))
    return _write_crontab(lines)


def _linux_uninstall() -> bool:
    lines = [ln for ln in _crontab_lines() if TASK_NAME not in ln]
    return _write_crontab(lines)


def _linux_status(cfg) -> str:
    return "registered" if any(TASK_NAME in ln for ln in _crontab_lines()) else "missing"


# ---- 统一入口 ----

def install(cfg) -> bool:
    if sys.platform == "win32":
        ok = _win_install(cfg)
    elif sys.platform == "darwin":
        ok = _mac_install(cfg)
    else:
        ok = _linux_install(cfg)
    if ok:
        cfg.scheduler_registered = True
        from .storage import store
        store.save_settings(cfg)
    return ok


def uninstall(cfg) -> bool:
    if sys.platform == "win32":
        ok = _win_uninstall()
    elif sys.platform == "darwin":
        ok = _mac_uninstall()
    else:
        ok = _linux_uninstall()
    if ok:
        cfg.scheduler_registered = False
        from .storage import store
        store.save_settings(cfg)
    return ok


def status(cfg) -> str:
    if sys.platform == "win32":
        return _win_status(cfg)
    if sys.platform == "darwin":
        return _mac_status(cfg)
    return _linux_status(cfg)
