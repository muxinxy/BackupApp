"""SFTP 上传器：paramiko。list() 用 listdir_attr 拿大小/时间。"""

import posixpath
from datetime import datetime

import paramiko

from ..model import SelfBackup
from .base import BACKUP_PREFIX, RemoteFile, Uploader


class SFTPUploader(Uploader):
    def __init__(self, sb: SelfBackup):
        if not sb.host:
            raise ValueError("SFTP 未配置主机地址")
        self.host = sb.host
        self.port = sb.port or 22
        self.user = sb.username
        self.pw = sb.password
        self.path = sb.remote_path.strip("/")

    def _connect(self) -> paramiko.SFTPClient:
        t = paramiko.Transport((self.host, self.port))
        t.connect(username=self.user, password=self.pw)
        return paramiko.SFTPClient.from_transport(t)

    def _remote(self, name: str = "") -> str:
        return posixpath.join(self.path, name) if self.path else name

    def test(self) -> tuple[bool, str]:
        try:
            with self._connect() as sftp:
                sftp.listdir(self.path or ".")
            return True, "连接成功"
        except Exception as e:
            return False, str(e)

    def _ensure_dir(self, sftp: paramiko.SFTPClient):
        cur = ""
        for part in self.path.split("/"):
            if not part:
                continue
            cur = f"{cur}/{part}" if cur else part
            try:
                sftp.stat(cur)
            except FileNotFoundError:
                sftp.mkdir(cur)

    def upload(self, local_path: str, remote_name: str) -> None:
        with self._connect() as sftp:
            if self.path:
                self._ensure_dir(sftp)
            sftp.put(local_path, self._remote(remote_name))

    def download(self, remote_name: str, local_path: str) -> None:
        with self._connect() as sftp:
            sftp.get(self._remote(remote_name), local_path)

    def list(self) -> list[RemoteFile]:
        with self._connect() as sftp:
            try:
                attrs = sftp.listdir_attr(self.path or ".")
            except FileNotFoundError:
                attrs = []
            out = []
            for a in attrs:
                if not a.filename.startswith(BACKUP_PREFIX):
                    continue
                mtime = ""
                if a.st_mtime:
                    mtime = datetime.fromtimestamp(a.st_mtime).isoformat()
                out.append(RemoteFile(name=a.filename, size=int(a.st_size),
                                      mtime=mtime))
            return out

    def delete(self, remote_name: str) -> None:
        with self._connect() as sftp:
            sftp.remove(self._remote(remote_name))
