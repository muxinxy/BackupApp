"""协议模块冒烟测试：WebDAV stub 服务器端到端验证自身备份/恢复流程。

用法: .venv\Scripts\python scripts\protocol_smoke.py
覆盖：上传/远程保留/本地副本剪枝/连通性测试/远程列表(大写 D: 命名空间、
href URL 解码)/下载恢复/删除/CLI self-* 接线/S3 错误路径。
"""

import os
import shutil
import subprocess
import sys
import tempfile
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from backupapp.protocols.base import make_uploader  # noqa: E402
from backupapp.protocols.runner import (  # noqa: E402
    run_self_backup, run_self_restore, list_remote_files, delete_remote_file)
from backupapp.storage import store  # noqa: E402
from backupapp.model import AppConfig  # noqa: E402


class DavHandler(BaseHTTPRequestHandler):
    """最小 WebDAV stub：扁平文件存储，支持 PROPFIND/PUT/GET/DELETE/MKCOL。

    - PROPFIND 用大写 <D:> 前缀（OpenList 风格），并返回大小/时间元数据
    - href 用 URL 编码形式（验证解码逻辑）
    """

    files: dict[str, bytes] = {}
    counts: dict[str, int] = {}  # 方法 -> 请求次数（验证 _ensure_dir 缓存/连接复用）

    def _send(self, code: int, body: bytes = b"", ctype: str = "text/xml"):
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_PROPFIND(self):
        self.counts["PROPFIND"] = self.counts.get("PROPFIND", 0) + 1
        import urllib.parse
        body = b'<?xml version="1.0"?><D:multistatus xmlns:D="DAV:">'
        for name in sorted(self.files):
            data = self.files[name]
            href = urllib.parse.quote(f"/{name}")
            body += (
                f'<D:response><D:href>{href}</D:href>'
                f'<D:propstat><D:prop>'
                f'<D:getcontentlength>{len(data)}</D:getcontentlength>'
                f'<D:getlastmodified>Mon, 01 Jan 2026 00:00:00 GMT</D:getlastmodified>'
                f'</D:prop></D:propstat></D:response>'
            ).encode()
        body += b"</D:multistatus>"
        self._send(207, body)

    def do_PUT(self):
        self.counts["PUT"] = self.counts.get("PUT", 0) + 1
        n = int(self.headers.get("Content-Length", 0))
        self.files[self.path.strip("/")] = self.rfile.read(n)
        self._send(201)

    def do_GET(self):
        self.counts["GET"] = self.counts.get("GET", 0) + 1
        name = self.path.strip("/")
        if name in self.files:
            self._send(200, self.files[name], ctype="application/octet-stream")
        else:
            self._send(404)

    def do_DELETE(self):
        self.files.pop(self.path.strip("/"), None)
        self._send(204)

    def do_MKCOL(self):
        self._send(201)

    def log_message(self, *args):
        pass


def main() -> None:
    srv = ThreadingHTTPServer(("127.0.0.1", 0), DavHandler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    base_url = f"http://127.0.0.1:{srv.server_port}"

    tmp = tempfile.mkdtemp(prefix="backupapp_proto_")
    store.set_data_root(tmp)
    store.save_app(AppConfig(id="proto", name="Protocol Test"))
    cfg = store.load_settings()
    sb = cfg.sb("webdav")
    sb.enabled = True
    sb.host = base_url
    sb.remote_path = "/backups"
    sb.retention = 2
    sb.local_copy = True
    cfg.self_backups["webdav"] = sb
    store.save_settings(cfg)

    # 三次备份：第三次应触发远程与本地剪枝（保留 2 份）
    for i in range(3):
        results = run_self_backup()
        r = results[0]
        assert r.ok, f"第 {i + 1} 次自身备份失败: {r.error}"
        # 文件名带本机设备名
        assert "_" in r.remote_name.split("backupapp_", 1)[1], \
            f"备份文件名缺设备名: {r.remote_name}"
    remote = sorted(DavHandler.files.keys())
    print(f"remote files: {remote}")
    assert len(remote) == 2, f"远程保留失效: {remote}"
    local = sorted(os.listdir(os.path.join(store.backups_dir())))
    assert len(local) == 2, f"本地保留失效: {local}"
    print(f"local copies: {local}")

    # 连通性测试
    ok, msg = make_uploader(sb).test()
    assert ok, f"test() 失败: {msg}"
    print(f"test(): {msg}")

    # 远程列表：大写 D: 命名空间 + href URL 解码 + 大小/时间元数据
    files = list_remote_files("webdav")
    assert len(files) == 2, f"list() 数量异常: {[f.name for f in files]}"
    f0 = files[0]
    assert f0.size > 0 and f0.mtime, f"元数据缺失: {f0}"
    print(f"list(): {f0.name} {f0.size}B {f0.mtime}")

    # 下载恢复：改坏本地数据 -> 恢复 -> 校验 apps 回来
    os.remove(os.path.join(store.data_dir(), "apps", "proto.json"))
    r = run_self_restore("webdav", f0.name)
    assert r.ok, f"恢复失败: {r.error}"
    assert os.path.isfile(os.path.join(store.data_dir(), "apps", "proto.json")), \
        "恢复后 apps 缺失"
    print(f"restore(): {r.remote_name} -> {r.files} files")
    # 安全网：应产生 self_restore_old_* 目录
    olds = [d for d in os.listdir(store.data_dir())
            if d.startswith("self_restore_old_")]
    assert olds, "恢复安全网目录缺失"
    print(f"safety net: {olds}")

    # 删除远程文件
    err = delete_remote_file("webdav", f0.name)
    assert err is None, f"删除失败: {err}"
    files_after = list_remote_files("webdav")
    assert len(files_after) == 1, f"删除后数量异常: {len(files_after)}"
    print(f"delete(): {f0.name} -> {len(files_after)} remaining")

    # 流式下载 + _ensure_dir 缓存：一次上传只需 1 次 PROPFIND（缓存后不再重复
    # 探测每个路径段），下载走 iter_bytes 但内容必须完整。
    DavHandler.counts.clear()
    up = make_uploader(sb)
    payload = os.path.join(tmp, "payload.bin")
    blob = os.urandom(3 * 1024 * 1024 + 12345)  # 跨多个 64KiB chunk
    with open(payload, "wb") as f:
        f.write(blob)
    up.upload(payload, "backupapp_probe_20260910_000000.zip")
    assert DavHandler.counts.get("PROPFIND", 0) == 1, \
        f"_ensure_dir 未缓存，PROPFIND={DavHandler.counts.get('PROPFIND')}"
    back = os.path.join(tmp, "payload_back.bin")
    up.download("backupapp_probe_20260910_000000.zip", back)
    with open(back, "rb") as f:
        assert f.read() == blob, "流式下载内容不一致"
    # 同实例第二次上传：目录已缓存，不应再发 PROPFIND
    up.upload(payload, "backupapp_probe2_20260910_000000.zip")
    assert DavHandler.counts.get("PROPFIND", 0) == 1, \
        f"复用实例后仍重复 PROPFIND: {DavHandler.counts.get('PROPFIND')}"
    up.close()
    print(f"stream download + ensure_dir cache ok (PROPFIND={DavHandler.counts['PROPFIND']})")

    # 多协议配置独立：S3 配置不影响 webdav
    cfg = store.load_settings()
    sb3 = cfg.sb("s3")
    sb3.enabled = True
    sb3.endpoint = "http://127.0.0.1:1"
    sb3.bucket = "no-such-bucket"
    cfg.self_backups["s3"] = sb3
    store.save_settings(cfg)
    assert store.load_settings().sb("webdav").host == base_url, \
        "S3 配置写入覆盖了 webdav"
    print("per-protocol config isolated: ok")

    # S3 错误路径：无法连接时应干净返回 (False, msg)
    ok3, msg3 = make_uploader(sb3).test()
    assert ok3 is False and isinstance(msg3, str), f"s3 错误路径异常: {ok3} {msg3}"
    print(f"s3 error path ok: {msg3[:60]}")

    # FTP 降级判定：仅 TLS 协商失败才降级明文，认证失败/网络错误必须照抛
    from ftplib import error_perm as _error_perm
    from backupapp.protocols import ftp as _ftp

    class _FakeTLS:
        """可编程的 FTP_TLS 替身：按阶段模拟失败。

        ftplib 的 FTP_TLS.connect() 内部完成 AUTH TLS，因此 TLS 不支持表现为
        connect 抛错；认证失败表现为 login 抛错（两者都是 error_perm）。
        """
        fail_with = None

        def connect(self, host, port, timeout=None):
            if self.fail_with == "connect":
                raise OSError("network down")
            if self.fail_with == "tls_perm":
                raise _error_perm("550 TLS config not available")

        def login(self, user, pw):
            if self.fail_with == "auth":
                raise _error_perm("530 Login incorrect")

        def prot_p(self):
            pass

        def close(self):
            pass

    class _FakePlain:
        """降级后的明文连接：总是成功（用于验证是否发生了降级）。"""

        def connect(self, host, port, timeout=None):
            pass

        def login(self, user, pw):
            pass

        def close(self):
            pass

    made = []

    def _make_plain():
        f = _FakePlain()
        made.append(f)
        return f

    orig_tls, orig_plain = _ftp.FTP_TLS, _ftp.FTP
    _ftp.FTP_TLS = _FakeTLS
    _ftp.FTP = _make_plain
    try:
        sb_ftp = _ftp.FTPUploader.__new__(_ftp.FTPUploader)
        sb_ftp.host, sb_ftp.port, sb_ftp.user, sb_ftp.pw = "h", 21, "u", "p"
        sb_ftp.path, sb_ftp.tls, sb_ftp.timeout = "", True, 5

        # TLS 协商被服务器拒绝 -> 降级明文（_login 用伪造的 FTP）
        _FakeTLS.fail_with = "tls_perm"
        made.clear()
        sb_ftp._connect()
        assert made, "TLS 被拒绝时应降级到明文 FTP"

        # 认证失败 -> 必须抛 error_perm，不得降级明文
        _FakeTLS.fail_with = "auth"
        made.clear()
        try:
            sb_ftp._connect()
        except _error_perm:
            pass
        else:
            raise AssertionError("认证失败不得降级明文")
        assert not made, "认证失败时不应新建明文连接"

        # 网络错误 -> 同样不得降级
        _FakeTLS.fail_with = "connect"
        made.clear()
        try:
            sb_ftp._connect()
        except OSError:
            pass
        else:
            raise AssertionError("网络错误不得降级明文")
        assert not made, "网络错误时不应新建明文连接"
    finally:
        _ftp.FTP_TLS, _ftp.FTP = orig_tls, orig_plain
    print("ftp tls fallback policy ok")

    # CLI 接线：独立进程跑 self-backup / self-list
    env = dict(os.environ)
    repo = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    cli = subprocess.run(
        [sys.executable, "-m", "backupapp", "--data-dir", tmp, "self-backup",
         "--protocol", "webdav"],
        capture_output=True, text=True, encoding="utf-8", errors="replace",
        env=env, cwd=repo)
    print(f"CLI self-backup exit={cli.returncode}")
    print(cli.stdout.strip()[-300:])
    assert cli.returncode == 0 and "OK" in cli.stdout, f"CLI 失败: {cli.stderr}"

    cli_list = subprocess.run(
        [sys.executable, "-m", "backupapp", "--data-dir", tmp,
         "self-list", "--protocol", "webdav"],
        capture_output=True, text=True, encoding="utf-8", errors="replace",
        env=env, cwd=repo)
    assert cli_list.returncode == 0 and "backupapp_" in cli_list.stdout, \
        f"CLI self-list 失败: {cli_list.stderr} {cli_list.stdout}"
    print(f"CLI self-list ok ({len(cli_list.stdout.strip().splitlines())} files)")

    # 多协议复用产物：同 (格式, 密码) 的协议共享一次打包。
    # 直接对 _run_one 的分组缓存做单元验证（共享 artifacts 字典 = 同一批运行）。
    from backupapp.protocols import runner as _runner
    calls = {"n": 0}
    _orig_build = _runner._build_archive

    def _counting_build(sb):
        calls["n"] += 1
        return _orig_build(sb)

    import copy as _copy
    cfg = store.load_settings()
    sb.local_copy = False
    sb.retention = 0
    sb_a = cfg.sb("webdav")
    sb_a.host, sb_a.remote_path = base_url, "/backups_a"
    sb_a.format, sb_a.archive_password = "zip", ""
    sb_b = _copy.deepcopy(sb_a)
    sb_b.remote_path = "/backups_b"  # 第二个目标，同格式同密码

    _runner._build_archive = _counting_build
    try:
        artifacts, temp_created = {}, []
        calls["n"] = 0
        r1 = _runner._run_one(sb_a, artifacts, temp_created)
        r2 = _runner._run_one(sb_b, artifacts, temp_created)
        assert r1.ok and r2.ok, (r1.error, r2.error)
        assert calls["n"] == 1, f"同组协议应只打包一次，实际 {calls['n']} 次"
        assert r1.files == 2, f"文件数应为 apps+settings，实际 {r1.files}"
        # 两个目标都应收到备份
        assert DavHandler.counts.get("PUT", 0) >= 2
        print(f"artifact reuse: packed {calls['n']}x for 2 protocols")
    finally:
        _runner._build_archive = _orig_build

    srv.shutdown()
    shutil.rmtree(tmp, ignore_errors=True)
    print("PROTOCOL SMOKE ALL PASS")


if __name__ == "__main__":
    main()
