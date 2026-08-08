"""协议模块冒烟测试：WebDAV stub 服务器端到端验证自身备份流程。

用法: .venv\Scripts\python scripts\protocol_smoke.py
覆盖：上传/远程保留/本地副本剪枝/连通性测试/CLI self-backup 接线/S3 错误路径。
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
from backupapp.protocols.runner import run_self_backup  # noqa: E402
from backupapp.storage import store  # noqa: E402
from backupapp.model import AppConfig  # noqa: E402


class DavHandler(BaseHTTPRequestHandler):
    """最小 WebDAV stub：扁平文件存储，支持 PROPFIND/PUT/DELETE/MKCOL。"""

    files: dict[str, bytes] = {}

    def _send(self, code: int, body: bytes = b""):
        self.send_response(code)
        self.send_header("Content-Type", "text/xml")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_PROPFIND(self):
        body = b'<?xml version="1.0"?><D:multistatus xmlns:D="DAV:">'
        for name in sorted(self.files):
            body += f'<D:response><D:href>/{name}</D:href></D:response>'.encode()
        body += b"</D:multistatus>"
        self._send(207, body)

    def do_PUT(self):
        n = int(self.headers.get("Content-Length", 0))
        self.files[self.path.strip("/")] = self.rfile.read(n)
        self._send(201)

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
    sb = cfg.self_backup
    sb.enabled = True
    sb.protocol = "webdav"
    sb.host = base_url
    sb.remote_path = "/backups"
    sb.retention = 2
    sb.local_copy = True
    store.save_settings(cfg)

    # 三次备份：第三次应触发远程与本地剪枝（保留 2 份）
    for i in range(3):
        r = run_self_backup()
        assert r.ok, f"第 {i + 1} 次自身备份失败: {r.error}"
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

    # S3 错误路径：无法连接时应干净返回 (False, msg)
    sb3 = store.load_settings().self_backup
    sb3.protocol = "s3"
    sb3.host = ""
    sb3.bucket = "no-such-bucket"
    sb3.endpoint = "http://127.0.0.1:1"
    ok3, msg3 = make_uploader(sb3).test()
    assert ok3 is False and isinstance(msg3, str), f"s3 错误路径异常: {ok3} {msg3}"
    print(f"s3 error path ok: {msg3[:60]}")

    # CLI 接线：独立进程跑 self-backup
    env = dict(os.environ)
    cli = subprocess.run(
        [sys.executable, "-m", "backupapp", "--data-dir", tmp, "self-backup"],
        capture_output=True, text=True, env=env,
        cwd=os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    print(f"CLI self-backup exit={cli.returncode}")
    print(cli.stdout.strip()[-300:])
    assert cli.returncode == 0 and "OK" in cli.stdout, f"CLI 失败: {cli.stderr}"

    srv.shutdown()
    shutil.rmtree(tmp, ignore_errors=True)
    print("PROTOCOL SMOKE ALL PASS")


if __name__ == "__main__":
    main()
