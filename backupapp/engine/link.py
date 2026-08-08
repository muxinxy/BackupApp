"""符号链接 / 目录联接：link 模式的核心。

Windows 上 junction(mklink /J) 无需管理员/开发者模式；symlink 需要。
链接模式下数据实际存放在 destination/live/<app_id>，源路径是指向它的链接。
"""

import os
import shutil
import subprocess
import sys


def is_link(path: str) -> bool:
    if os.path.islink(path):
        return True
    try:
        if os.path.isjunction(path):  # py3.12+
            return True
    except (AttributeError, OSError):
        pass
    # 兜底启发式：reparse point（junction）的 realpath 与 abspath 不同
    try:
        return os.path.exists(path) and os.path.realpath(path) != os.path.abspath(path)
    except OSError:
        return False


def remove_link(path: str) -> None:
    if not is_link(path):
        return
    try:
        os.unlink(path)
    except OSError:
        os.rmdir(path)  # junction 按目录删


def create_link(source: str, target: str, link_type: str) -> None:
    """source 必须是尚不存在的路径；target 应为绝对路径。"""
    if sys.platform == "win32":
        kind = "J" if link_type == "junction" else "D"
        r = subprocess.run(["cmd", "/c", "mklink", f"/{kind}", source, target],
                           capture_output=True, text=True)
        if r.returncode != 0:
            raise RuntimeError(f"创建链接失败: {r.stderr.strip() or r.stdout.strip()}")
    else:
        os.symlink(os.path.abspath(target), source)


def live_dir_for(dest: str, app_id: str) -> str:
    return os.path.join(dest, "live", app_id)


def ensure_linked(source: str, live_dir: str, link_type: str) -> bool:
    """link 模式就位：若 source 还不是链接，把其内容搬入 live_dir 并建链接。

    返回 True 表示本次做了搬迁+建链；False 表示已就位。
    """
    if is_link(source):
        return False
    if os.path.exists(source):
        if os.path.exists(live_dir):
            for item in os.listdir(source):
                shutil.move(os.path.join(source, item), live_dir)
            os.rmdir(source)
        else:
            shutil.move(source, live_dir)
    os.makedirs(os.path.dirname(live_dir), exist_ok=True)
    create_link(source, live_dir, link_type)
    return True
