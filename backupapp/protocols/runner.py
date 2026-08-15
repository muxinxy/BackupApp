"""自身备份编排：打包 data 目录（apps/ + settings.json）-> 上传远程 -> 远程保留 -> 本地副本。

支持多协议独立配置：run_self_backup 遍历所有启用的协议；run_self_restore 按协议恢复。
"""

import os
import shutil
import tempfile
from dataclasses import dataclass
from datetime import datetime

from .. import logging, security
from ..engine import compress
from ..storage import store
from .base import device_name, make_uploader, prune_remote


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


@dataclass
class SelfRestoreResult:
    ok: bool
    protocol: str = ""
    remote_name: str = ""
    files: int = 0
    error: str | None = None


def _build_archive(sb) -> tuple[str, int, int]:
    """打包 apps/ + settings.json 到临时归档，返回 (路径, 文件数, 字节数)。

    归档根为固定名 data/（内含 apps/ 与 settings.json）：
    打包源目录 basename 即归档根，固定名保证 restore 能定位。
    """
    data = store.data_dir()
    staging = tempfile.mkdtemp(prefix="backupapp_selfbackup_")
    root = os.path.join(staging, "data")
    apps_dir = os.path.join(root, "apps")
    os.makedirs(apps_dir, exist_ok=True)
    app_files = [f for f in os.listdir(os.path.join(data, "apps")) if f.endswith(".json")]
    for name in app_files:
        shutil.copy2(os.path.join(data, "apps", name), os.path.join(apps_dir, name))
    shutil.copy2(os.path.join(data, "settings.json"), os.path.join(root, "settings.json"))
    snapshot = datetime.now().strftime("%Y%m%d_%H%M%S")
    # 文件名带本机设备名：backupapp_<device>_<ts>.<ext>
    archive = os.path.join(tempfile.gettempdir(),
                           f"backupapp_{device_name()}_{snapshot}.{sb.format}")
    files, size = compress.create_archive([root], archive, sb.format,
                                          sb.archive_password, [])
    shutil.rmtree(staging, ignore_errors=True)
    return archive, files + 1, size


def _archive_name(archive: str) -> str:
    return os.path.basename(archive)


def run_self_backup(protocol: str | None = None) -> list[SelfBackupResult]:
    """执行自身备份。protocol 指定时只跑该协议，否则跑所有已启用的协议。"""
    cfg = store.load_settings()
    sbs = [cfg.sb(protocol)] if protocol else cfg.enabled_sbs()
    if not sbs:
        return [SelfBackupResult(False, error="自身备份未启用（设置中勾选至少一个协议）")]
    results = []
    for sb in sbs:
        results.append(_run_one(sb))
    return results


def _run_one(sb) -> SelfBackupResult:
    try:
        sb = security.plain_sb(sb)  # 凭据解密（dpapi/keyring）
        archive, files, size = _build_archive(sb)
        remote_name = _archive_name(archive)
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


def list_remote_files(protocol: str) -> list:
    """返回远程备份文件元数据列表（按文件名倒序=新到旧）。"""
    cfg = store.load_settings()
    sb = security.plain_sb(cfg.sb(protocol))
    u = make_uploader(sb)
    files = u.list()
    files.sort(key=lambda f: f.name, reverse=True)
    return files


def _find_self_root(staging: str) -> str | None:
    """在解压目录中定位自身备份根（含 apps/ 与 settings.json）。

    apps/ 可能为空目录（尚未配置任何应用），zip 解压后空目录可能不落盘，
    因此以 settings.json 为定位锚点，apps/ 允许缺失（视为空）。
    兼容三种归档根：
    - 顶层：staging/apps（最早版本）
    - data/：staging/data/apps（v2 新格式）
    - 随机子目录：staging/<随机名>/apps（v1 旧版 exe 打包整个 staging 目录）
    """
    for root in (staging, os.path.join(staging, "data")):
        if os.path.isfile(os.path.join(root, "settings.json")):
            return root
    # v1 旧格式：顶层单个子目录内含 settings.json
    for name in os.listdir(staging):
        p = os.path.join(staging, name)
        if os.path.isdir(p) and os.path.isfile(os.path.join(p, "settings.json")):
            return p
    return None


def run_self_restore(protocol: str, remote_name: str,
                     overwrite: bool = True) -> SelfRestoreResult:
    """从远程下载指定备份并恢复 data 目录（apps/ + settings.json）。

    overwrite=False 时跳过本机已存在的应用（相同 id），其余照常恢复。
    安全网：恢复前把现有 data/apps 与 settings.json 移到 .old 时间戳目录。
    """
    try:
        cfg = store.load_settings()
        sb = security.plain_sb(cfg.sb(protocol))
        u = make_uploader(sb)
        data = store.data_dir()
        tmp = tempfile.mkdtemp(prefix="backupapp_restore_")
        local_zip = os.path.join(tmp, remote_name)
        u.download(remote_name, local_zip)
        staging = os.path.join(tmp, "staging")
        compress.extract_archive(local_zip, staging, sb.archive_password)
        root = _find_self_root(staging)
        if root is None:
            raise ValueError("归档内容不是自身备份（缺 settings.json）")
        apps_dir = os.path.join(root, "apps")
        settings_file = os.path.join(root, "settings.json")
        # 备份当前数据到 .old 目录
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        old_dir = os.path.join(data, f"self_restore_old_{stamp}")
        for sub in ("apps", "settings.json"):
            src = os.path.join(data, sub)
            if os.path.exists(src):
                os.makedirs(old_dir, exist_ok=True)
                shutil.move(src, os.path.join(old_dir, sub))
        # 恢复（apps 为空目录时 zip 可能不含该条目，这里兜底创建）
        os.makedirs(os.path.join(data, "apps"), exist_ok=True)
        if os.path.isdir(apps_dir):
            if overwrite:
                shutil.copytree(apps_dir, os.path.join(data, "apps"),
                                dirs_exist_ok=True)
            else:
                # 仅恢复本机不存在的应用（同 id 保留现有）
                for name in os.listdir(apps_dir):
                    if name.endswith(".json") and not os.path.exists(
                            os.path.join(data, "apps", name)):
                        shutil.copy2(os.path.join(apps_dir, name),
                                     os.path.join(data, "apps", name))
        shutil.copy2(settings_file, os.path.join(data, "settings.json"))
        n = len([f for f in os.listdir(os.path.join(data, "apps"))
                 if f.endswith(".json")])
        shutil.rmtree(tmp, ignore_errors=True)
        logging.get_logger().info("self-restore ok %s://%s/%s (%d apps)",
                                  sb.protocol, sb.host, remote_name, n)
        return SelfRestoreResult(True, protocol=protocol, remote_name=remote_name,
                                 files=n + 1)
    except Exception as e:
        logging.get_logger().error("self-restore failed: %s", e)
        return SelfRestoreResult(False, protocol=protocol, error=str(e))


def delete_remote_file(protocol: str, remote_name: str) -> str | None:
    """删除远程备份文件，返回错误信息（None=成功）。"""
    try:
        cfg = store.load_settings()
        sb = security.plain_sb(cfg.sb(protocol))
        make_uploader(sb).delete(remote_name)
        return None
    except Exception as e:
        return str(e)
