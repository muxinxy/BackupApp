"""远程上传协议统一接口：webdav / s3 / ftp / sftp。

远程备份命名统一为 backupapp_<设备名>_<YYYYMMDD_HHMMSS>.<ext>（设备名缺省为空），
按文件名排序即按时间排序，远程保留策略按此剪枝。
"""

import re
import socket
from abc import ABC, abstractmethod
from dataclasses import dataclass

from ..model import SelfBackup

BACKUP_PREFIX = "backupapp_"
SNAP_RE = re.compile(rf"^{BACKUP_PREFIX}[\w.-]*_\d{{8}}_\d{{6}}\.")


def device_name() -> str:
    """本机设备名（用于备份文件名，清洗成文件系统安全字符）。"""
    name = socket.gethostname()
    return re.sub(r"[^\w.-]", "_", name) or "host"


@dataclass
class RemoteFile:
    name: str
    size: int = 0
    mtime: str = ""  # 备份时间，ISO 格式


class Uploader(ABC):
    @abstractmethod
    def test(self) -> tuple[bool, str]:
        """连通性测试，返回 (ok, 描述)。"""

    @abstractmethod
    def upload(self, local_path: str, remote_name: str) -> None:
        """上传本地文件到远程，remote_name 为文件名（不含目录）。"""

    @abstractmethod
    def download(self, remote_name: str, local_path: str) -> None:
        """下载远程文件到本地，remote_name 为文件名（不含目录）。"""

    @abstractmethod
    def list(self) -> list[RemoteFile]:
        """返回远程与本应用备份匹配的文件元数据列表。"""

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
    files = sorted(u.list(), key=lambda f: f.name, reverse=True)
    removed = 0
    for f in files[keep:]:
        try:
            u.delete(f.name)
            removed += 1
        except Exception:
            pass
    return removed
