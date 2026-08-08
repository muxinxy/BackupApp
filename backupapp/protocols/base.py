"""远程上传协议统一接口：webdav / s3 / ftp / sftp。

远程备份命名统一为 backupapp_<YYYYMMDD_HHMMSS>.<ext>，按文件名排序即按时间排序，
远程保留策略按此剪枝。
"""

import re
from abc import ABC, abstractmethod

from ..model import SelfBackup

BACKUP_PREFIX = "backupapp_"
SNAP_RE = re.compile(rf"^{BACKUP_PREFIX}\d{{8}}_\d{{6}}\.")


class Uploader(ABC):
    @abstractmethod
    def test(self) -> tuple[bool, str]:
        """连通性测试，返回 (ok, 描述)。"""

    @abstractmethod
    def upload(self, local_path: str, remote_name: str) -> None:
        """上传本地文件到远程，remote_name 为文件名（不含目录）。"""

    @abstractmethod
    def list(self) -> list[str]:
        """返回远程与本应用备份匹配的文件名列表。"""

    @abstractmethod
    def delete(self, remote_name: str) -> None:
        """删除远程文件（不存在时视为成功）。"""


def make_uploader(sb: SelfBackup) -> Uploader:
    from . import ftp, s3, sftp, webdav
    if sb.protocol == "webdav":
        return webdav.WebDAVUploader(sb)
    if sb.protocol == "s3":
        return s3.S3Uploader(sb)
    if sb.protocol == "ftp":
        return ftp.FTPUploader(sb)
    if sb.protocol == "sftp":
        return sftp.SFTPUploader(sb)
    raise ValueError(f"不支持的协议: {sb.protocol}")


def prune_remote(u: Uploader, keep: int) -> int:
    """保留最近 keep 份远程备份，返回删除数。keep<=0 视为保留全部。"""
    if keep <= 0:
        return 0
    names = sorted(u.list(), reverse=True)
    removed = 0
    for name in names[keep:]:
        try:
            u.delete(name)
            removed += 1
        except Exception:
            pass
    return removed
