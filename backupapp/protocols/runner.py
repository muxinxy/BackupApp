"""自身备份编排：打包 data 目录（apps/ + settings.json）-> 上传远程 -> 远程保留 -> 本地副本。"""

import os
import shutil
import tempfile
from dataclasses import dataclass
from datetime import datetime

from .. import logging, security
from ..engine import compress
from ..storage import store
from .base import make_uploader, prune_remote


@dataclass
class SelfBackupResult:
    ok: bool
    plan_key: str = "self-backup"
    remote_name: str = ""
    remote: str = ""
    local_path: str = ""
    files: int = 0
    bytes: int = 0
    pruned: int = 0
    error: str | None = None


def _build_archive(sb) -> tuple[str, int, int]:
    """打包 apps/ + settings.json 到临时归档，返回 (路径, 文件数, 字节数)。"""
    data = store.data_dir()
    staging = tempfile.mkdtemp(prefix="backupapp_selfbackup_")
    os.makedirs(os.path.join(staging, "apps"), exist_ok=True)
    app_files = [f for f in os.listdir(os.path.join(data, "apps")) if f.endswith(".json")]
    for name in app_files:
        shutil.copy2(os.path.join(data, "apps", name), os.path.join(staging, "apps", name))
    shutil.copy2(os.path.join(data, "settings.json"), os.path.join(staging, "settings.json"))
    snapshot = datetime.now().strftime("%Y%m%d_%H%M%S")
    archive = os.path.join(tempfile.gettempdir(), f"backupapp_{snapshot}.{sb.format}")
    files, size = compress.create_archive([staging], archive, sb.format,
                                          sb.archive_password, [])
    shutil.rmtree(staging, ignore_errors=True)
    return archive, files + 1, size


def run_self_backup() -> SelfBackupResult:
    cfg = store.load_settings()
    sb = cfg.self_backup
    if not sb.enabled:
        return SelfBackupResult(False, error="自身备份未启用（settings.json -> selfBackup.enabled）")
    try:
        sb = security.plain_sb(sb)  # 凭据解密（dpapi/keyring）
        archive, files, size = _build_archive(sb)
        remote_name = os.path.basename(archive)
        local = ""
        pruned = 0
        if sb.local_copy:
            from ..engine import retention
            local = os.path.join(store.backups_dir(), remote_name)
            shutil.move(archive, local)
            archive = local
            pruned += retention.prune(store.backups_dir(), "backupapp",
                                      sb.retention, False)
        u = make_uploader(sb)
        u.upload(archive, remote_name)
        pruned += prune_remote(u, sb.retention)
        if not sb.local_copy:
            os.remove(archive)
        logging.get_logger().info(
            "self-backup ok -> %s://%s/%s (%d bytes, pruned %d)",
            sb.protocol, sb.host, remote_name, size, pruned)
        return SelfBackupResult(True, remote_name=remote_name,
                                remote=f"{sb.protocol}://{sb.host}",
                                local_path=local, files=files, bytes=size,
                                pruned=pruned)
    except Exception as e:
        logging.get_logger().error("self-backup failed: %s", e)
        return SelfBackupResult(False, error=str(e))
