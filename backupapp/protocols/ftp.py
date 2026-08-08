"""FTP 上传器：ftplib（stdlib）。use_ssl 时用 FTP_TLS（显式 TLS）。"""

from ftplib import FTP, FTP_TLS, error_perm

from ..model import SelfBackup
from .base import BACKUP_PREFIX, Uploader


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

    def list(self) -> list[str]:
        with self._connect() as ftp:
            if self.path:
                self._ensure_dir(ftp)
            try:
                names = ftp.nlst()
            except error_perm:
                names = []
        return [n for n in names if n.startswith(BACKUP_PREFIX)]

    def delete(self, remote_name: str) -> None:
        with self._connect() as ftp:
            if self.path:
                self._ensure_dir(ftp)
            ftp.delete(remote_name)
