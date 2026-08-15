"""FTP 上传器：ftplib（stdlib）。use_ssl 时用 FTP_TLS（显式 TLS）。

list() 优先 MLSD（自带大小/时间），不支持时回退 nlst + SIZE。
"""

from datetime import datetime
from ftplib import FTP, FTP_TLS, error_perm

from ..model import SelfBackup
from .base import BACKUP_PREFIX, RemoteFile, Uploader


class FTPUploader(Uploader):
    def __init__(self, sb: SelfBackup):
        if not sb.host:
            raise ValueError("FTP 未配置主机地址")
        self.host = sb.host
        self.port = sb.port or 21
        self.user = sb.username
        self.pw = sb.password
        self.path = sb.remote_path.strip("/")
        self.tls = sb.use_ssl

    def _connect(self) -> FTP:
        ftp = FTP_TLS() if self.tls else FTP()
        ftp.connect(self.host, self.port, timeout=30)
        ftp.login(self.user or "anonymous", self.pw)
        if self.tls:
            ftp.prot_p()
        return ftp

    def test(self) -> tuple[bool, str]:
        try:
            with self._connect() as ftp:
                ftp.pwd()
            return True, "连接成功"
        except Exception as e:
            return False, str(e)

    def _ensure_dir(self, ftp: FTP):
        cur = ""
        for part in self.path.split("/"):
            if not part:
                continue
            cur = f"{cur}/{part}" if cur else part
            try:
                ftp.cwd(cur)
            except error_perm:
                ftp.mkd(cur)

    def upload(self, local_path: str, remote_name: str) -> None:
        with self._connect() as ftp:
            if self.path:
                self._ensure_dir(ftp)
            with open(local_path, "rb") as f:
                ftp.storbinary(f"STOR {remote_name}", f)

    def download(self, remote_name: str, local_path: str) -> None:
        with self._connect() as ftp:
            if self.path:
                self._ensure_dir(ftp)
            with open(local_path, "wb") as f:
                ftp.retrbinary(f"RETR {remote_name}", f.write)

    def list(self) -> list[RemoteFile]:
        with self._connect() as ftp:
            if self.path:
                self._ensure_dir(ftp)
            out = []
            if self.path:
                ftp.cwd(self.path)
            # 优先 MLSD（标准），失败回退 nlst + SIZE
            try:
                for name, facts in ftp.mlsd():
                    if not name.startswith(BACKUP_PREFIX):
                        continue
                    size = int(facts.get("size", 0) or 0)
                    mtime = ""
                    if facts.get("modify"):
                        try:
                            mtime = datetime.strptime(
                                facts["modify"], "%Y%m%d%H%M%S").isoformat()
                        except ValueError:
                            pass
                    out.append(RemoteFile(name=name, size=size, mtime=mtime))
            except error_perm:
                for name in ftp.nlst():
                    if not name.startswith(BACKUP_PREFIX):
                        continue
                    try:
                        size = ftp.size(name) or 0
                    except error_perm:
                        size = 0
                    out.append(RemoteFile(name=name, size=size))
            return out

    def delete(self, remote_name: str) -> None:
        with self._connect() as ftp:
            if self.path:
                self._ensure_dir(ftp)
            ftp.delete(remote_name)
