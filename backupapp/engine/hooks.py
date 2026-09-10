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
import tempfile

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


def _kill_tree(proc: subprocess.Popen) -> None:
    """结束钩子进程及其后代。

    shell=True 时直接杀子进程只杀到 shell，脚本（bat/ps1/sh）拉起的孙进程会
    变成孤儿继续跑。Windows 用 taskkill /T 杀整棵树，POSIX 用进程组。
    """
    if proc.poll() is not None:
        return
    try:
        if sys.platform == "win32":
            flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
            subprocess.run(["taskkill", "/F", "/T", "/PID", str(proc.pid)],
                           capture_output=True, creationflags=flags, timeout=10)
        else:
            import os as _os
            import signal as _signal
            _os.killpg(_os.getpgid(proc.pid), _signal.SIGKILL)
    except Exception:
        pass  # 尽力而为：杀不掉也要让上层拿到超时错误
    try:
        proc.kill()
    except Exception:
        pass
    try:
        proc.wait(timeout=5)
    except Exception:
        pass


# 钩子输出上限：直接 PIPE + communicate() 会把全部输出缓存在内存，脚本刷屏
# 可能吃满内存。改为写入临时文件（落盘而非内存），只读取尾部。
_TAIL_BYTES = 64 * 1024


def _read_tail(f) -> str:
    """读取临时文件末尾 _TAIL_BYTES 字节并解码。

    直接对文件对象 seek/read（TemporaryFile 的 .name 在 POSIX 下是整数 fd，
    不能当路径打开）。
    """
    try:
        f.flush()
        f.seek(0, os.SEEK_END)
        size = f.tell()
        f.seek(max(0, size - _TAIL_BYTES))
        data = f.read()
    except (OSError, ValueError):
        return ""
    text = data.decode("utf-8", errors="replace")
    return text if size <= _TAIL_BYTES else _("…（输出过长已截断）\n") + text


def run_hook(cmd: str, timeout: int, plan_key: str, when: str) -> None:
    """执行钩子命令，失败抛 RuntimeError（含超时）。"""
    if not cmd.strip():
        return
    kwargs = {}
    if sys.platform == "win32":
        kwargs["creationflags"] = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    else:
        kwargs["start_new_session"] = True  # 独立进程组，便于整组终止
    out_f = tempfile.TemporaryFile()
    err_f = tempfile.TemporaryFile()
    try:
        proc = subprocess.Popen(_script_command(cmd), shell=True,
                                stdout=out_f, stderr=err_f, **kwargs)
        try:
            proc.wait(timeout=timeout)
        except subprocess.TimeoutExpired:
            _kill_tree(proc)
            raise RuntimeError(
                _("{when}钩子执行超时（>{timeout}s）: {cmd}").format(
                    when=when, timeout=timeout, cmd=cmd))
        if proc.returncode != 0:
            detail_lines = (_read_tail(out_f).strip().splitlines()[-3:]
                            + _read_tail(err_f).strip().splitlines()[-3:])
            detail = "\n".join(ln for ln in detail_lines if ln) or _("无输出")
            raise RuntimeError(
                _("{when}钩子退出码 {code}:\n{detail}").format(
                    when=when, code=proc.returncode, detail=detail))
        out = _read_tail(out_f).strip()
        if out:
            logging.get_logger().info(_("[%s] %s钩子输出: %s"),
                                      plan_key, when, out)
    finally:
        out_f.close()
        err_f.close()
