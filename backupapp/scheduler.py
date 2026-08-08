"""系统计划任务：全局任务（backup --all）与单计划任务（backup --plan app/plan）。

win: schtasks / macOS: launchctl + LaunchAgents plist / linux: crontab。
Windows 分支为实测目标，mac/linux 为最佳努力实现。
任务名按需生成，删除计划时须同步取消对应任务。
"""

import csv
import io
import os
import re
import shlex
import subprocess
import sys
import time

TASK_NAME = "BackupAppGlobalBackup"

# 已注册任务列表缓存（TTL 3 秒）：避免每次刷新/点击都起子进程查询
_TASK_CACHE: tuple[float, set[str]] | None = None


def _exe() -> str:
    if getattr(sys, "frozen", False):
        return f'"{sys.executable}"'
    return f'"{sys.executable}" -m backupapp'


def app_command(cfg) -> str:
    """全局备份命令：计划任务与文档中的入口，退出码反映成败。"""
    args = " ".join(cfg.scheduler.args) or "backup --all"
    return f"{_exe()} {args}"


def plan_command(app_id: str, plan_id: str) -> str:
    """单个计划的备份命令。"""
    return f"{_exe()} backup --plan {app_id}/{plan_id}"


def plan_task_name(app_id: str, plan_id: str) -> str:
    """单个计划的系统任务名；ID 含 schtasks 非法字符时替换。"""
    def _safe(s: str) -> str:
        s = re.sub(r'[\\/:*?"<>|]', "_", s)
        return (s.strip(" .") or "plan")[:64]
    return f"BackupApp_{_safe(app_id)}_{_safe(plan_id)}"


def _run(cmd: list[str]) -> subprocess.CompletedProcess:
    kwargs = {}
    if sys.platform == "win32":
        kwargs["creationflags"] = subprocess.CREATE_NO_WINDOW  # 避免从 GUI 弹出终端
    return subprocess.run(cmd, capture_output=True, text=True, **kwargs)


# ---- Windows ----

_WIN_DAYS = ("MON", "TUE", "WED", "THU", "FRI", "SAT", "SUN")


def _win_sc(sc: tuple) -> list[str]:
    """sc = (frequency, time, day_of_week, interval)。"""
    freq, time, day, interval = sc
    if freq == "atLogon":
        return ["/sc", "onlogon"]
    if freq == "weekly":
        # schtasks /d 接受英文缩写（中文本地化下数字 1-7 报"值无效"）
        return ["/sc", "weekly", "/st", time, "/d", _WIN_DAYS[max(0, min(6, day - 1))]]
    if freq == "days":
        return ["/sc", "daily", "/mo", str(max(1, min(365, interval)))]
    if freq == "hourly":
        return ["/sc", "hourly", "/mo", str(max(1, min(23, interval)))]
    if freq == "minutely":
        return ["/sc", "minute", "/mo", str(max(1, min(1439, interval)))]
    return ["/sc", "daily", "/st", time]


def _win_install(sc: tuple, task_name: str, command: str) -> str:
    cmd = ["schtasks", "/create", "/tn", task_name, "/tr", command,
           "/f"] + _win_sc(sc)
    r = _run(cmd)
    if r.returncode == 0:
        return ""
    err = (r.stderr or r.stdout or "未知错误").strip()
    if sc[0] == "atLogon":
        err += "（登录时任务需要以管理员身份运行）"
    return err


def _win_uninstall(task_name: str) -> str:
    r = _run(["schtasks", "/delete", "/tn", task_name, "/f"])
    return "" if r.returncode == 0 else (r.stderr or "删除失败").strip()


def _win_status(task_name: str, command: str) -> str:
    r = _run(["schtasks", "/query", "/tn", task_name, "/v", "/fo", "list"])
    if r.returncode != 0:
        return "missing"
    for line in r.stdout.splitlines():
        if "Task To Run" in line and command not in line:
            return "pathMismatch"
    return "registered"


# ---- macOS ----

def _mac_plist(sc: tuple, task_name: str, command: str) -> str:
    freq, time, _day, interval = sc
    args_xml = "\n".join(f"    <string>{a}</string>" for a in shlex.split(command))
    if freq == "atLogon":
        cal = "<key>RunAtLoad</key><true/>"
    elif freq in ("days", "hourly", "minutely"):
        # launchd 无"N天/小时/分钟"日历项，退化为自启动间隔（秒），最佳努力
        secs = interval * {"days": 86400, "hourly": 3600, "minutely": 60}[freq]
        cal = f"<key>StartInterval</key><integer>{secs}</integer>"
    else:
        hh, mm = (time or "02:30").split(":")
        cal = (f"<key>StartCalendarInterval</key><dict>"
               f"<key>Hour</key><integer>{int(hh)}</integer>"
               f"<key>Minute</key><integer>{int(mm)}</integer></dict>")
    return f"""<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
  <key>Label</key><string>{task_name}</string>
  <key>ProgramArguments</key><array>
{args_xml}
  </array>
  {cal}
</dict></plist>
"""


def _mac_plist_path(task_name: str) -> str:
    return os.path.expanduser(f"~/Library/LaunchAgents/{task_name}.plist")


def _mac_install(sc: tuple, task_name: str, command: str) -> str:
    p = _mac_plist_path(task_name)
    with open(p, "w", encoding="utf-8") as f:
        f.write(_mac_plist(sc, task_name, command))
    r = _run(["launchctl", "load", "-w", p])
    return "" if r.returncode == 0 else "launchctl load 失败"


def _mac_uninstall(task_name: str) -> str:
    _run(["launchctl", "unload", p := _mac_plist_path(task_name)])
    if os.path.exists(p):
        os.remove(p)
    return ""


def _mac_status(task_name: str) -> str:
    r = _run(["launchctl", "list"])
    return "registered" if task_name in r.stdout else "missing"


# ---- Linux ----

def _cron_line(sc: tuple, task_name: str, command: str) -> str:
    freq, time, day, interval = sc
    if freq == "atLogon":
        return f"@reboot {command} # {task_name}"
    if freq == "minutely":
        return f"*/{max(1, interval)} * * * * {command} # {task_name}"
    if freq == "hourly":
        return f"0 */{max(1, min(23, interval))} * * * {command} # {task_name}"
    hh, mm = (time or "02:30").split(":")
    if freq == "days":
        return f"{mm} {hh} */{max(1, min(365, interval))} * * {command} # {task_name}"
    if freq == "weekly":
        return f"{mm} {hh} * * {day % 7} {command} # {task_name}"  # 1=Mon..7=Sun -> cron 0=Sun..6=Sat
    return f"{mm} {hh} * * * {command} # {task_name}"


def _crontab_lines() -> list[str]:
    r = _run(["crontab", "-l"])
    return r.stdout.splitlines() if r.returncode == 0 else []


def _write_crontab(lines: list[str]) -> bool:
    kwargs = {}
    if sys.platform == "win32":
        kwargs["creationflags"] = subprocess.CREATE_NO_WINDOW
    r = subprocess.run(["crontab", "-"], input="\n".join(lines) + "\n",
                       capture_output=True, text=True, **kwargs)
    return r.returncode == 0


def _linux_install(sc: tuple, task_name: str, command: str) -> str:
    lines = [ln for ln in _crontab_lines() if task_name not in ln]
    lines.append(_cron_line(sc, task_name, command))
    return "" if _write_crontab(lines) else "crontab 写入失败"


def _linux_uninstall(task_name: str) -> str:
    lines = [ln for ln in _crontab_lines() if task_name not in ln]
    return "" if _write_crontab(lines) else "crontab 写入失败"


def _linux_status(task_name: str) -> str:
    return "registered" if any(task_name in ln for ln in _crontab_lines()) else "missing"


# ---- 统一入口 ----

def _plan_schedule(cfg, app_id: str, plan_id: str) -> tuple:
    """单个计划任务的排期 (frequency, time, day_of_week, interval)：自定义优先，否则与全局一致。"""
    from .storage import store
    pair = store.load_plan(app_id, plan_id)
    if pair and pair[1].schedule_mode == "custom":
        p = pair[1]
        return (p.schedule_frequency or "daily",
                p.schedule_time or "02:30",
                p.schedule_day_of_week or 1,
                p.schedule_interval or 1)
    s = cfg.scheduler
    return (s.frequency, s.time, s.day_of_week, s.interval)


def _platform_install(sc: tuple, task_name: str, command: str) -> str:
    if sys.platform == "win32":
        return _win_install(sc, task_name, command)
    if sys.platform == "darwin":
        return _mac_install(sc, task_name, command)
    return _linux_install(sc, task_name, command)


def _platform_uninstall(task_name: str) -> str:
    if sys.platform == "win32":
        return _win_uninstall(task_name)
    if sys.platform == "darwin":
        return _mac_uninstall(task_name)
    return _linux_uninstall(task_name)


def _platform_status(task_name: str, command: str) -> str:
    if sys.platform == "win32":
        return _win_status(task_name, command)
    if sys.platform == "darwin":
        return _mac_status(task_name)
    return _linux_status(task_name)


def install(cfg) -> str:
    """注册全局计划任务。返回空串 = 成功，否则为错误信息。"""
    s = cfg.scheduler
    sc = (s.frequency, s.time, s.day_of_week, s.interval)
    err = _platform_install(sc, TASK_NAME, app_command(cfg))
    if not err:
        cfg.scheduler_registered = True
        from .storage import store
        store.save_settings(cfg)
    return err


def uninstall(cfg) -> str:
    """取消注册全局计划任务。返回空串 = 成功，否则为错误信息。"""
    err = _platform_uninstall(TASK_NAME)
    if not err:
        cfg.scheduler_registered = False
        from .storage import store
        store.save_settings(cfg)
    return err


def status(cfg) -> str:
    return _platform_status(TASK_NAME, app_command(cfg))


def plan_install(cfg, app_id: str, plan_id: str) -> str:
    """注册单个计划的计划任务（排期取计划自定义值或全局设置）。"""
    err = _platform_install(_plan_schedule(cfg, app_id, plan_id),
                            plan_task_name(app_id, plan_id),
                            plan_command(app_id, plan_id))
    if not err:
        _invalidate_task_cache()
    return err


def plan_uninstall(app_id: str, plan_id: str) -> str:
    """取消注册单个计划的计划任务。"""
    err = _platform_uninstall(plan_task_name(app_id, plan_id))
    if not err:
        _invalidate_task_cache()
    return err


def plan_status(cfg, app_id: str, plan_id: str) -> str:
    return _platform_status(plan_task_name(app_id, plan_id),
                            plan_command(app_id, plan_id))


def _invalidate_task_cache() -> None:
    global _TASK_CACHE
    _TASK_CACHE = None


def registered_plan_tasks() -> set[str]:
    """返回当前已注册的单计划任务名集合（一次系统查询，不含全局任务，3 秒缓存）。"""
    global _TASK_CACHE
    now = time.time()
    if _TASK_CACHE is not None and now - _TASK_CACHE[0] < 3.0:
        return set(_TASK_CACHE[1])
    if sys.platform == "win32":
        r = _run(["schtasks", "/query", "/fo", "csv", "/nh"])
        names = ({row[0].lstrip("\\") for row in csv.reader(io.StringIO(r.stdout))
                  if row and row[0].lstrip("\\").startswith("BackupApp_")}
                 if r.returncode == 0 else set())
    elif sys.platform == "darwin":
        r = _run(["launchctl", "list"])
        names = {ln.split()[-1] for ln in r.stdout.splitlines() if "BackupApp_" in ln}
    else:
        names = {ln.split("# ")[-1].strip() for ln in _crontab_lines()
                 if "BackupApp_" in ln}
    _TASK_CACHE = (now, names)
    return set(names)
