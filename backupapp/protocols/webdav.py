"""WebDAV 上传器：httpx，PROPFIND/PUT/GET/DELETE/MKCOL。

兼容 OpenList 等网关：
- 命名空间按标准 {DAV:}（OpenList 返回大写 <D:> 前缀，即同一命名空间）；
- href 做 URL 解码（网关可能返回 %20 等编码）；
- 下载 GET 302 到签名地址（如 OSS）时 follow_redirects=True：
  跨域重定向 httpx 自动剥离 Authorization，且不带 Referer，可绕过 OSS 防盗链 403。
"""

import xml.etree.ElementTree as ET
from datetime import datetime
from urllib.parse import unquote

import httpx

from ..model import SelfBackup
from .base import BACKUP_PREFIX, RemoteFile, Uploader

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
        kw.setdefault("follow_redirects", True)
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

    def download(self, remote_name: str, local_path: str) -> None:
        r = self._req("GET", self._url(remote_name))
        if r.status_code not in (200, 206):
            raise RuntimeError(f"下载失败: HTTP {r.status_code} {r.text[:200]}")
        with open(local_path, "wb") as f:
            f.write(r.content)

    def list(self) -> list[RemoteFile]:
        r = self._req("PROPFIND", self._url(), headers={"Depth": "1"})
        if r.status_code not in (200, 207):
            return []
        files: list[RemoteFile] = []
        root = ET.fromstring(r.text)
        for resp in root.iter(f"{_DAV}response"):
            href_el = resp.find(f"{_DAV}href")
            if href_el is None or not href_el.text:
                continue
            name = unquote(href_el.text.rstrip("/").split("/")[-1])
            if not name.startswith(BACKUP_PREFIX):
                continue
            size, mtime = 0, ""
            for prop in resp.iter(f"{_DAV}prop"):
                size_el = prop.find(f"{_DAV}getcontentlength")
                if size_el is not None and size_el.text:
                    try:
                        size = int(size_el.text)
                    except ValueError:
                        pass
                mt_el = prop.find(f"{_DAV}getlastmodified")
                if mt_el is not None and mt_el.text:
                    try:
                        # RFC 1123 -> ISO
                        mtime = datetime.strptime(mt_el.text,
                                                  "%a, %d %b %Y %H:%M:%S %Z").isoformat()
                    except ValueError:
                        mtime = mt_el.text
            files.append(RemoteFile(name=name, size=size, mtime=mtime))
        return files

    def delete(self, remote_name: str) -> None:
        r = self._req("DELETE", self._url(remote_name))
        if r.status_code not in (200, 204, 404):
            raise RuntimeError(f"删除失败: HTTP {r.status_code}")
