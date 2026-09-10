"""符号链接 / 目录联接：link 模式的核心。

Windows 上 junction(mklink /J) 无需管理员/开发者模式；symlink 需要。
链接模式下数据实际存放在 destination/live/<app_id>，源路径是指向它的链接。
"""

import os
import shutil
import stat
import subprocess
import sys

from ..i18n import _


def is_link(path: str) -> bool:
    """判断路径本身是否是链接/联接（而非其父目录是链接）。

    Windows 上不能靠 realpath != abspath 判断：父目录是 junction/符号链接
    （如 OneDrive、重定向的用户目录）时，普通真实目录也会被判成链接，
    后续 remove_link 会试图删除真实目录。改为查 reparse point 属性。
    """
    if os.path.islink(path):
        return True
    try:
        if os.path.isjunction(path):  # py3.12+
            return True
    except (AttributeError, OSError):
        pass
    if sys.platform == "win32":
        try:
            st = os.lstat(path)
        except OSError:
            return False
        attrs = getattr(st, "st_file_attributes", 0)
        reparse = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)
        return bool(attrs & reparse)
    return False


def remove_link(path: str) -> None:
    """删除链接/联接本身，不触碰其目标，也不删除真实目录。"""
    if not is_link(path):
        return
    try:
        os.unlink(path)
    except OSError:
        # junction 在 Windows 上按目录处理；仅当确认是链接时才走 rmdir
        if is_link(path):
            try:
                os.rmdir(path)
            except OSError:
                pass


def create_link(source: str, target: str, link_type: str) -> None:
    """source 必须是尚不存在的路径；target 应为绝对路径。"""
    if sys.platform == "win32":
        kind = "J" if link_type == "junction" else "D"
        flags = 0x08000000  # CREATE_NO_WINDOW：避免从 GUI 弹出终端
        # mklink 的错误输出是系统 ANSI 码页（中文系统 GBK）。用默认 text=True
        # 在 UTF-8 模式（PYTHONUTF8=1）下 reader 线程解码失败并静默清空输出，
        # 真正的错误信息会丢失。显式按 mbcs 解码，与 scheduler._run 一致。
        r = subprocess.run(["cmd", "/c", "mklink", f"/{kind}", source, target],
                           capture_output=True, encoding="mbcs", errors="replace",
                           creationflags=flags)
        if r.returncode != 0:
            detail = (r.stderr or "").strip() or (r.stdout or "").strip()
            raise RuntimeError(
                _("创建链接失败: {detail}").format(
                    detail=detail or _("未知错误")))
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
