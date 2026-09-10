"""SFTP 上传器：paramiko。list() 用 listdir_attr 拿大小/时间。

远程路径统一用绝对路径（/bequest），避免相对路径与 cwd 叠加歧义。
"""

import contextlib
import posixpath
from datetime import datetime

import paramiko

from ..i18n import _
from ..model import SelfBackup
from .base import BACKUP_PREFIX, RemoteFile, Uploader


class SFTPUploader(Uploader):
    def __init__(self, sb: SelfBackup):
        if not sb.host:
            raise ValueError(_("SFTP 未配置主机地址"))
        self.host = sb.host
        self.port = sb.port or 22
        self.user = sb.username
        self.pw = sb.password
        self.path = sb.remote_path.strip("/")
        self.timeout = sb.timeout or 10

    @contextlib.contextmanager
    def _session(self):
        """建立一个 SFTP 会话并保证 SSH transport 一并关闭。

        SFTPClient.close() 只关 SFTP 通道，底层 transport/socket 要等 GC 才关；
        每次 list/upload/delete 都新建连接，不显式关闭会累积 TCP 会话。
        """
        t = paramiko.Transport((self.host, self.port))
        try:
            t.banner_timeout = self.timeout
            t.connect(username=self.user, password=self.pw)
            sftp = paramiko.SFTPClient.from_transport(t)
            try:
                yield sftp
            finally:
                sftp.close()
        finally:
            t.close()

    def _remote(self, name: str = "") -> str:
        """绝对路径：/bequest 或 /bequest/name。"""
        base = f"/{self.path}" if self.path else ""
        return posixpath.join(base, name) if name else base

    def test(self) -> tuple[bool, str]:
        try:
            with self._session() as sftp:
                sftp.listdir(self._remote())
            return True, _("连接成功")
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
        with self._session() as sftp:
            if self.path:
                self._ensure_dir(sftp)
            # 用 open().write() 流式上传：部分 SFTP 网关（如本站点）不支持
            # paramiko 的 put()（多 request 握手被服务器断开）
            with open(local_path, "rb") as f:
                with sftp.open(self._remote(remote_name), "wb") as rf:
                    while True:
                        chunk = f.read(1 << 16)
                        if not chunk:
                            break
                        rf.write(chunk)

    def download(self, remote_name: str, local_path: str) -> None:
        with self._session() as sftp:
            # 同 upload：open().read() 流式下载，部分网关不支持 get()
            with sftp.open(self._remote(remote_name), "rb") as rf:
                with open(local_path, "wb") as f:
                    while True:
                        chunk = rf.read(1 << 16)
                        if not chunk:
                            break
                        f.write(chunk)

    def list(self) -> list[RemoteFile]:
        with self._session() as sftp:
            try:
                attrs = sftp.listdir_attr(self._remote())
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
        with self._session() as sftp:
            sftp.remove(self._remote(remote_name))
