"""备份计划命令/脚本钩子：备份前(pre)与备份后(post)执行，可设超时。

命令按 shell 执行（Windows cmd / Linux sh），支持任意命令或脚本路径。
非零退出码或超时视为失败。
"""

import subprocess

from .. import logging


def run_hook(cmd: str, timeout: int, plan_key: str, when: str) -> None:
    """执行钩子命令，失败抛 RuntimeError（含超时）。"""
    if not cmd.strip():
        return
    try:
        r = subprocess.run(
            cmd, shell=True, timeout=timeout,
            capture_output=True, text=True, encoding="utf-8", errors="replace")
        if r.returncode != 0:
            tail = (r.stdout or "").strip().splitlines()[-3:]
            tail += (r.stderr or "").strip().splitlines()[-3:]
            detail = "\n".join(line for line in tail if line) or "无输出"
            raise RuntimeError(f"{when}钩子退出码 {r.returncode}:\n{detail}")
        if r.stdout and r.stdout.strip():
            logging.get_logger().info("[%s] %s钩子输出: %s",
                                      plan_key, when, r.stdout.strip()[-200:])
    except subprocess.TimeoutExpired:
        raise RuntimeError(f"{when}钩子执行超时（>{timeout}s）: {cmd}")
