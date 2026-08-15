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

    def _send(self, code: int, body: bytes = b"", ctype: str = "text/xml"):
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_PROPFIND(self):
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
        n = int(self.headers.get("Content-Length", 0))
        self.files[self.path.strip("/")] = self.rfile.read(n)
        self._send(201)

    def do_GET(self):
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

    srv.shutdown()
    shutil.rmtree(tmp, ignore_errors=True)
    print("PROTOCOL SMOKE ALL PASS")


if __name__ == "__main__":
    main()
