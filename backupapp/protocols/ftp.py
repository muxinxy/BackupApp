"""FTP 上传器：ftplib（stdlib）。use_ssl 时用 FTP_TLS（显式 TLS）。

list() 优先 MLSD（自带大小/时间），不支持时回退 nlst + SIZE。
远程路径统一用绝对路径操作，避免相对 cwd 叠加导致 550 CD issue。
数据通道（PASV）偶发超时时自动重连重试。
"""

import logging
import ssl
from datetime import datetime
from ftplib import FTP, FTP_TLS, error_perm, error_temp

from ..i18n import _
from ..model import SelfBackup
from .base import BACKUP_PREFIX, RemoteFile, Uploader


class FTPUploader(Uploader):
    def __init__(self, sb: SelfBackup):
        if not sb.host:
            raise ValueError(_("FTP 未配置主机地址"))
        self.host = sb.host
        self.port = sb.port or 21
        self.user = sb.username
        self.pw = sb.password
        self.path = sb.remote_path.strip("/")
        self.tls = sb.use_ssl
        self.timeout = sb.timeout or 10

    def _connect(self) -> FTP:
        """连接并登录；use_ssl 时尝试 FTP_TLS，仅当服务器不支持 TLS 时降级普通 FTP。

        降级判定按阶段区分：ftplib 的 FTP_TLS.connect() 内部就完成 AUTH TLS，
        因此只有 connect 阶段失败才说明"服务器不支持 TLS"。login/prot_p 阶段
        失败（认证错误同样是 error_perm）必须照抛——否则密码会在本该加密的
        连接上明文发送。
        """
        if not self.tls:
            return self._login(FTP())
        ftp = FTP_TLS()
        try:
            ftp.connect(self.host, self.port, timeout=self.timeout)
        except (error_perm, error_temp, ssl.SSLError) as e:
            # AUTH TLS 被服务器拒绝/协商失败（如网关 550 TLS config）-> 降级明文
            self._close_quietly(ftp)
            logging.getLogger(__name__).warning(
                "ftp server refused TLS (%s); falling back to plaintext", e)
            return self._login(FTP())
        except Exception:
            self._close_quietly(ftp)
            raise
        try:
            ftp.login(self.user or "anonymous", self.pw)
            ftp.prot_p()
        except Exception:
            self._close_quietly(ftp)
            raise
        return ftp

    @staticmethod
    def _close_quietly(ftp: FTP) -> None:
        try:
            ftp.close()
        except Exception:
            pass

    def _login(self, ftp: FTP) -> FTP:
        ftp.connect(self.host, self.port, timeout=self.timeout)
        ftp.login(self.user or "anonymous", self.pw)
        return ftp

    def _binary(self, ftp: FTP):
        """切换二进制模式：retrbinary 不自动设 TYPE I，ASCII 下某些服务器
        传输会卡死/拒绝（SIZE not allowed in ASCII mode）。"""
        ftp.voidcmd("TYPE I")

    def test(self) -> tuple[bool, str]:
        try:
            with self._connect() as ftp:
                ftp.pwd()
            return True, _("连接成功")
        except Exception as e:
            return False, str(e)

    def _ensure_dir(self, ftp: FTP):
        """逐级创建远程绝对路径并进入（/bequest -> mkdir bequest）。"""
        cur = ""
        for part in self.path.split("/"):
            if not part:
                continue
            cur = f"{cur}/{part}" if cur else part
            try:
                ftp.cwd(cur)
            except error_perm:
                ftp.mkd(cur)
                ftp.cwd(cur)

    def _retry(self, fn):
        """数据通道（PASV 连接）偶发慢/超时：重试 2 次。

        部分 FTP 网关（如本工具测试的 192.129.221.213）建立被动数据连接
        时偶发超过 timeout（10s），重连重试即可成功。
        """
        last = None
        for attempt in range(3):
            try:
                return fn()
            except TimeoutError as e:
                last = e
                logging.getLogger(__name__).warning(
                    "ftp data channel timeout (attempt %d/3): %s", attempt + 1, e)
        raise last

    def upload(self, local_path: str, remote_name: str) -> None:
        def _do():
            with self._connect() as ftp:
                if self.path:
                    self._ensure_dir(ftp)
                with open(local_path, "rb") as f:
                    ftp.storbinary(f"STOR {remote_name}", f)
        self._retry(_do)

    def download(self, remote_name: str, local_path: str) -> None:
        def _do():
            with self._connect() as ftp:
                if self.path:
                    self._ensure_dir(ftp)
                self._binary(ftp)  # ASCII 下 RETR 会卡死/报错
                with open(local_path, "wb") as f:
                    ftp.retrbinary(f"RETR {remote_name}", f.write)
        self._retry(_do)

    def list(self) -> list[RemoteFile]:
        with self._connect() as ftp:
            if self.path:
                self._ensure_dir(ftp)  # 已 cwd 进远程路径，勿再 cwd 叠加
            out = []
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
                self._binary(ftp)
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
