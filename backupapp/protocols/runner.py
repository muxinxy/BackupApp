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
from ..i18n import _
from ..storage import lock, store
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

    归档放在独立临时目录里：文件名保持远程命名规范不变（backupapp_<设备>_<时间戳>），
    同一次运行内若有多个"格式+密码"分组，各自目录互不冲突。
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
    # 同一秒内的两次自身备份会算出同名文件，第二次直接覆盖第一次：
    # 本地副本目录（启用时）与远程同用该名，按其已用快照避让。
    from ..engine import retention
    used = {retention.snapshot_of(e)
            for e in retention.list_entries(store.backups_dir(), "backupapp")}
    used.discard("")
    snapshot = retention.unique_snapshot_from(used, snapshot)
    # 文件名带本机设备名：backupapp_<device>_<ts>.<ext>
    outdir = tempfile.mkdtemp(prefix="backupapp_artifact_")
    archive = os.path.join(outdir,
                           f"backupapp_{device_name()}_{snapshot}.{sb.format}")
    files, size = compress.create_archive([root], archive, sb.format,
                                          sb.archive_password, [])
    shutil.rmtree(staging, ignore_errors=True)
    # create_archive 遍历的 root 已含 settings.json，无需再 +1
    return archive, files, size


def _archive_name(archive: str) -> str:
    return os.path.basename(archive)


def run_self_backup(protocol: str | None = None) -> list[SelfBackupResult]:
    """执行自身备份。protocol 指定时只跑该协议，否则跑所有已启用的协议。

    同一份 data 目录按 (格式, 归档密码) 分组：同组协议只打包一次并复用产物，
    避免启用 3 个协议就把整个数据目录压缩 3 遍。临时归档在本函数结束时统一清理
    （不能在每个协议上传后立即删，否则后续协议无产物可用）。
    """
    cfg = store.load_settings()
    sbs = [cfg.sb(protocol)] if protocol else cfg.enabled_sbs()
    if not sbs:
        return [SelfBackupResult(False, error=_("自身备份未启用（设置中勾选至少一个协议）"))]
    artifacts: dict[tuple[str, str], tuple[str, int, int]] = {}
    temp_created: list[str] = []
    results = []
    try:
        for sb in sbs:
            results.append(_run_one(sb, artifacts, temp_created))
    finally:
        for path in temp_created:
            if os.path.exists(path):
                shutil.rmtree(os.path.dirname(path), ignore_errors=True)
    return results


def _run_one(sb, artifacts=None, temp_created=None) -> SelfBackupResult:
    artifacts = {} if artifacts is None else artifacts
    temp_created = [] if temp_created is None else temp_created
    try:
        sb = security.plain_sb(sb)  # 凭据解密（dpapi/keyring）
        with lock.DataLock(lock.lock_path()):
            return _run_one_locked(sb, artifacts, temp_created)
    except RuntimeError as e:  # 锁被其他备份进程占用
        return SelfBackupResult(False, error=str(e))
    except Exception as e:
        logging.get_logger().error("self-backup failed: %s", e)
        return SelfBackupResult(False, error=str(e))


def _run_one_locked(sb, artifacts, temp_created) -> SelfBackupResult:
    """持锁执行；异常交给 _run_one 统一记日志并转成失败结果。"""
    key = (sb.format, sb.archive_password or "")
    if key in artifacts:
        archive, files, size = artifacts[key]  # 复用同组已打包的产物
    else:
        archive, files, size = _build_archive(sb)
        temp_created.append(archive)
        artifacts[key] = (archive, files, size)
    remote_name = _archive_name(archive)
    local = ""
    pruned = 0
    if sb.local_copy:
        from ..engine import retention
        local = os.path.join(store.backups_dir(), remote_name)
        if os.path.abspath(archive) != os.path.abspath(local):
            shutil.move(archive, local)
            # 后续同组协议直接复用本地副本，不再重新打包/搬运
            artifacts[key] = (local, files, size)
            if archive in temp_created:
                temp_created.remove(archive)
            archive = local
        pruned += retention.prune(store.backups_dir(), "backupapp",
                                  sb.retention, False)
    u = make_uploader(sb)
    try:
        u.upload(archive, remote_name)
        pruned += prune_remote(u, sb.retention)
    finally:
        u.close()
    logging.get_logger().info(
        "self-backup ok -> %s://%s/%s (%d bytes, pruned %d)",
        sb.protocol, sb.host, remote_name, size, pruned)
    return SelfBackupResult(True, remote_name=remote_name,
                            remote=f"{sb.protocol}://{sb.host}",
                            local_path=local, files=files, bytes=size,
                            pruned=pruned)


def list_remote_files(protocol: str) -> list:
    """返回远程备份文件元数据列表（按快照时间倒序=新到旧）。"""
    from ..engine.retention import snapshot_key
    cfg = store.load_settings()
    sb = security.plain_sb(cfg.sb(protocol))
    u = make_uploader(sb)
    try:
        files = u.list()
    finally:
        u.close()
    files.sort(key=lambda f: snapshot_key(f.name), reverse=True)
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


def _prune_old_dirs(data: str, keep: int = 3) -> int:
    """清理 data/self_restore_old_* 安全网目录，只保留最近 keep 份。

    每次自身恢复都会新建一个安全网目录，从不清理会无限增长占满磁盘。
    目录名按时间戳命名，按名称倒序即按时间倒序。
    """
    try:
        names = [n for n in os.listdir(data) if n.startswith("self_restore_old_")]
    except OSError:
        return 0
    names.sort(reverse=True)
    removed = 0
    for name in names[keep:]:
        try:
            shutil.rmtree(os.path.join(data, name), ignore_errors=True)
            removed += 1
        except OSError:
            pass
    return removed


def run_self_restore(protocol: str, remote_name: str,
                     overwrite: bool = True) -> SelfRestoreResult:
    """从远程下载指定备份并恢复 data 目录（apps/ + settings.json）。

    overwrite=False 时跳过本机已存在的应用（相同 id），其余照常恢复。
    安全网：恢复前把现有 data/apps 与 settings.json 移到 .old 时间戳目录。
    """
    try:
        with lock.DataLock(lock.lock_path()):
            return _run_self_restore_locked(protocol, remote_name, overwrite)
    except RuntimeError as e:  # 锁被其他备份进程占用
        return SelfRestoreResult(False, protocol=protocol, error=str(e))
    except Exception as e:
        logging.get_logger().error("self-restore failed: %s", e)
        return SelfRestoreResult(False, protocol=protocol, error=str(e))


def _run_self_restore_locked(protocol: str, remote_name: str,
                             overwrite: bool) -> SelfRestoreResult:
    cfg = store.load_settings()
    sb = security.plain_sb(cfg.sb(protocol))
    u = make_uploader(sb)
    data = store.data_dir()
    tmp = tempfile.mkdtemp(prefix="backupapp_restore_")
    try:
        local_zip = os.path.join(tmp, remote_name)
        u.download(remote_name, local_zip)
        staging = os.path.join(tmp, "staging")
        compress.extract_archive(local_zip, staging, sb.archive_password)
        root = _find_self_root(staging)
        if root is None:
            raise ValueError(_("归档内容不是自身备份（缺 settings.json）"))
        apps_dir = os.path.join(root, "apps")
        settings_file = os.path.join(root, "settings.json")
        # 备份当前数据到 .old 目录
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        old_dir = os.path.join(data, f"self_restore_old_{stamp}")
        moved = []
        for sub in ("apps", "settings.json"):
            src = os.path.join(data, sub)
            if os.path.exists(src):
                os.makedirs(old_dir, exist_ok=True)
                shutil.move(src, os.path.join(old_dir, sub))
                moved.append(sub)
        try:
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
        except BaseException:
            # 失败回滚：删掉半成品，把 .old 里的原数据搬回来，
            # 否则用户数据只剩在 self_restore_old_* 里、当前数据残缺
            for sub in moved:
                cur = os.path.join(data, sub)
                if os.path.isdir(cur):
                    shutil.rmtree(cur, ignore_errors=True)
                elif os.path.exists(cur):
                    try:
                        os.remove(cur)
                    except OSError:
                        pass
                try:
                    shutil.move(os.path.join(old_dir, sub), cur)
                except OSError as e:
                    logging.get_logger().error(
                        _("self-restore: 回滚失败，数据保留在 %s: %s"), old_dir, e)
            logging.get_logger().warning(_("self-restore: 失败已回滚"))
            raise
        n = len([f for f in os.listdir(os.path.join(data, "apps"))
                 if f.endswith(".json")])
        _prune_old_dirs(data)
        logging.get_logger().info("self-restore ok %s://%s/%s (%d apps)",
                                  sb.protocol, sb.host, remote_name, n)
        return SelfRestoreResult(True, protocol=protocol, remote_name=remote_name,
                                 files=n + 1)
    finally:
        # 失败路径同样清理：否则每次失败都留下一份完整归档在临时目录
        u.close()
        shutil.rmtree(tmp, ignore_errors=True)


def delete_remote_file(protocol: str, remote_name: str) -> str | None:
    """删除远程备份文件，返回错误信息（None=成功）。"""
    u = None
    try:
        cfg = store.load_settings()
        sb = security.plain_sb(cfg.sb(protocol))
        u = make_uploader(sb)
        u.delete(remote_name)
        return None
    except Exception as e:
        return str(e)
    finally:
        if u is not None:
            u.close()
