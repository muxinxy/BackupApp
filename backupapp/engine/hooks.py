"""备份计划命令/脚本钩子：备份前(pre)与备份后(post)执行，可设超时。

命令按 shell 执行（Windows cmd / Linux sh），支持任意命令或脚本路径。
命令为脚本文件路径时按当前平台自动包装解释器：
  Windows .bat/.cmd -> 直接执行；.ps1 -> powershell -File
  mac/Linux .sh    -> sh
非零退出码或超时视为失败。
"""

import os
import subprocess
import sys

from .. import logging
from ..i18n import _


def _script_command(cmd: str) -> str:
    """钩子命令是脚本文件路径时，包装成当前平台 shell 可执行的命令串。

    仅当去掉外层引号后整串等于一个存在的脚本文件才包装（路径可含空格）；
    否则原样返回（可能是 `net stop X` 之类的内联命令或带参数的命令）。
    """
    p = cmd.strip()
    if len(p) >= 2 and p[0] == p[-1] == '"':
        p = p[1:-1]
    if not os.path.isfile(p):
        return cmd
    ext = os.path.splitext(p)[1].lower()
    if ext == ".ps1":
        if sys.platform == "win32":
            return f'powershell -NoProfile -ExecutionPolicy Bypass -File "{p}"'
        # mac/linux 上若有 pwsh 也可执行 ps1
        import shutil
        if shutil.which("pwsh"):
            return f'pwsh -NoProfile -File "{p}"'
        return cmd
    if ext in (".bat", ".cmd") and sys.platform == "win32":
        return f'"{p}"'
    if ext == ".sh" and sys.platform != "win32":
        return f'sh "{p}"'
    return cmd


def run_hook(cmd: str, timeout: int, plan_key: str, when: str) -> None:
    """执行钩子命令，失败抛 RuntimeError（含超时）。"""
    if not cmd.strip():
        return
    try:
        r = subprocess.run(
            _script_command(cmd), shell=True, timeout=timeout,
            capture_output=True, text=True, encoding="utf-8", errors="replace")
        if r.returncode != 0:
            tail = (r.stdout or "").strip().splitlines()[-3:]
            tail += (r.stderr or "").strip().splitlines()[-3:]
            detail = "\n".join(line for line in tail if line) or _("无输出")
            raise RuntimeError(
                _("{when}钩子退出码 {code}:\n{detail}").format(
                    when=when, code=r.returncode, detail=detail))
        if r.stdout and r.stdout.strip():
            logging.get_logger().info(_("[%s] %s钩子输出: %s"),
                                      plan_key, when, r.stdout.strip()[-200:])
    except subprocess.TimeoutExpired:
        raise RuntimeError(
            _("{when}钩子执行超时（>{timeout}s）: {cmd}").format(
                when=when, timeout=timeout, cmd=cmd))
