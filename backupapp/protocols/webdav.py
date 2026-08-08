"""WebDAV 上传器：httpx，PROPFIND/PUT/DELETE/MKCOL。"""

import xml.etree.ElementTree as ET

import httpx

from ..model import SelfBackup
from .base import BACKUP_PREFIX, Uploader

_DAV = "{DAV:}"


class WebDAVUploader(Uploader):
    def __init__(self, sb: SelfBackup):
        if not sb.host:
            raise ValueError("WebDAV 未配置主机地址")
        self.base = sb.host.rstrip("/")
        self.path = sb.remote_path.strip("/")
        self.auth = (sb.username, sb.password) if sb.username else None

    def _url(self, name: str = "") -> str:
        return f"{self.base}/{self.path}/{name}" if name else f"{self.base}/{self.path}"

    def _req(self, method: str, url: str, **kw) -> httpx.Response:
        return httpx.request(method, url, auth=self.auth, timeout=30, **kw)

    def test(self) -> tuple[bool, str]:
        try:
            r = self._req("PROPFIND", self._url())
            return (True, "连接成功") if r.status_code in (200, 207) \
                else (False, f"HTTP {r.status_code}")
        except Exception as e:
            return False, str(e)

    def _ensure_dir(self):
        if self._req("PROPFIND", self._url()).status_code in (200, 207):
            return
        cur = self.base
        for part in self.path.split("/"):
            if not part:
                continue
            cur = f"{cur}/{part}"
            if self._req("PROPFIND", cur).status_code not in (200, 207):
                self._req("MKCOL", cur)

    def upload(self, local_path: str, remote_name: str) -> None:
        self._ensure_dir()
        with open(local_path, "rb") as f:
            r = self._req("PUT", self._url(remote_name), content=f)
        if r.status_code not in (200, 201, 204):
            raise RuntimeError(f"上传失败: HTTP {r.status_code} {r.text[:200]}")

    def list(self) -> list[str]:
        r = self._req("PROPFIND", self._url(), headers={"Depth": "1"})
        if r.status_code not in (200, 207):
            return []
        names = []
        for href in ET.fromstring(r.text).iter(f"{_DAV}href"):
            name = (href.text or "").rstrip("/").split("/")[-1]
            if name.startswith(BACKUP_PREFIX):
                names.append(name)
        return names

    def delete(self, remote_name: str) -> None:
        r = self._req("DELETE", self._url(remote_name))
        if r.status_code not in (200, 204, 404):
            raise RuntimeError(f"删除失败: HTTP {r.status_code}")
