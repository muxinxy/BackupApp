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

from ..i18n import _
from ..model import SelfBackup
from .base import BACKUP_PREFIX, RemoteFile, Uploader

_DAV = "{DAV:}"


class WebDAVUploader(Uploader):
    def __init__(self, sb: SelfBackup):
        if not sb.host:
            raise ValueError(_("WebDAV 未配置主机地址"))
        self.base = sb.host.rstrip("/")
        self.path = sb.remote_path.strip("/")
        self.auth = (sb.username, sb.password) if sb.username else None
        self.timeout = sb.timeout or 10
        # 复用单个 Client：模块级 httpx.request 每次都会新建连接池并重新
        # TCP+TLS 握手，多文件备份时开销显著。
        self._client = httpx.Client(auth=self.auth, timeout=self.timeout,
                                    follow_redirects=True)
        self._dir_ready = False  # _ensure_dir 只在实例内成功执行一次

    def close(self) -> None:
        self._client.close()

    def __enter__(self) -> "WebDAVUploader":
        return self

    def __exit__(self, *exc) -> None:
        self.close()

    def _url(self, name: str = "") -> str:
        return f"{self.base}/{self.path}/{name}" if name else f"{self.base}/{self.path}"

    def _req(self, method: str, url: str, **kw) -> httpx.Response:
        return self._client.request(method, url, **kw)

    def test(self) -> tuple[bool, str]:
        try:
            r = self._req("PROPFIND", self._url())
            return (True, _("连接成功")) if r.status_code in (200, 207) \
                else (False, _("HTTP {status}").format(status=r.status_code))
        except Exception as e:
            return False, str(e)

    def _ensure_dir(self):
        if self._dir_ready:
            return
        if self._req("PROPFIND", self._url()).status_code in (200, 207):
            self._dir_ready = True
            return
        cur = self.base
        for part in self.path.split("/"):
            if not part:
                continue
            cur = f"{cur}/{part}"
            if self._req("PROPFIND", cur).status_code not in (200, 207):
                self._req("MKCOL", cur)
        self._dir_ready = True

    def upload(self, local_path: str, remote_name: str) -> None:
        self._ensure_dir()
        with open(local_path, "rb") as f:
            r = self._req("PUT", self._url(remote_name), content=f)
        if r.status_code not in (200, 201, 204):
            raise RuntimeError(
                _("上传失败: HTTP {status} {body}").format(
                    status=r.status_code, body=r.text[:200]))

    def download(self, remote_name: str, local_path: str) -> None:
        # 流式下载：备份归档可能 GB 级，r.content 会把整包读进内存后 OOM
        with self._client.stream("GET", self._url(remote_name)) as r:
            if r.status_code not in (200, 206):
                r.read()
                raise RuntimeError(
                    _("下载失败: HTTP {status} {body}").format(
                        status=r.status_code, body=r.text[:200]))
            with open(local_path, "wb") as f:
                for chunk in r.iter_bytes(chunk_size=1 << 16):
                    f.write(chunk)

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
            raise RuntimeError(
                _("删除失败: HTTP {status}").format(status=r.status_code))
