"""恢复引擎：restore_plan。

copy 模式：源路径先改名为 .old 再解压/拷贝回去（安全网）。
link 模式：确保源路径是指向 live 目录的链接（数据本来就在备份目录）。
"""

import os
import shutil
import tempfile
from dataclasses import dataclass, field
from datetime import datetime

from .. import logging
from ..i18n import _
from ..storage import lock, store
from . import compress, link as linkmod, paths, retention


@dataclass
class RestoreResult:
    ok: bool
    plan_key: str
    snapshot: str = ""
    target: str = ""
    error: str | None = None


def restore_plan(plan_key: str, snapshot: str | None = None) -> RestoreResult:
    """恢复单个计划；加 DataLock（CLI/计划任务同样经过这里，恢复会改写源目录）。"""
    try:
        with lock.DataLock(lock.lock_path()):
            return _restore_plan_locked(plan_key, snapshot)
    except RuntimeError as e:
        logging.get_logger().warning("restore skipped %s: %s", plan_key, e)
        return RestoreResult(False, plan_key, error=str(e))
    except Exception as e:
        logging.get_logger().error("restore failed %s: %s", plan_key, e)
        return RestoreResult(False, plan_key, error=str(e))


def _prune_old_siblings(source: str, keep: int = 3) -> int:
    """清理 <source>.<时间戳>.old 安全网目录，只保留最近 keep 份。

    每次 copy 模式恢复都会留下一个 .old 目录，从不清理会无限增长。
    目录名以时间戳结尾，按名称倒序即按时间倒序。
    """
    parent = os.path.dirname(source) or "."
    base = os.path.basename(source)
    try:
        names = [n for n in os.listdir(parent)
                 if n.startswith(base + ".") and n.endswith(".old")]
    except OSError:
        return 0
    names.sort(reverse=True)
    removed = 0
    for name in names[keep:]:
        p = os.path.join(parent, name)
        try:
            if os.path.isdir(p):
                shutil.rmtree(p, ignore_errors=True)
            else:
                os.remove(p)
            removed += 1
        except OSError:
            pass
    return removed


def _restore_plan_locked(plan_key: str, snapshot: str | None) -> RestoreResult:
    try:
        pair = store.load_plan(*plan_key.split("/", 1))
        if not pair:
            raise ValueError(_("计划不存在: {plan_key}").format(plan_key=plan_key))
        app, plan = pair
        if not plan.sources:
            raise ValueError(
                _("计划 {plan_key} 没有配置源路径").format(plan_key=plan_key))
        source = paths.expand(plan.sources[0])
        dest = paths.expand(plan.destination)
        live_dir = linkmod.live_dir_for(dest, app.id)

        entries = retention.list_entries(dest, app.id)
        if not entries:
            raise ValueError(
                _("{dest} 下没有 {app_id} 的备份").format(dest=dest, app_id=app.id))
        entry = next((e for e in entries if not snapshot or snapshot in e), entries[0])
        if snapshot and not (snapshot in entry):
            raise ValueError(
                _("找不到快照 {snapshot}，可用: {available}").format(
                    snapshot=snapshot,
                    available=[retention.snapshot_of(e) for e in entries]))

        if plan.restore_mode == "link":
            if linkmod.is_link(source):
                pass  # 已就位
            elif not os.path.exists(live_dir):
                linkmod.ensure_linked(source, live_dir, plan.link_type)
            else:
                raise ValueError(
                    _("live 目录 {live_dir} 已存在且 {source} 是真实目录，请手动处理")
                    .format(live_dir=live_dir, source=source))
        else:
            # 先解压到临时目录，再动源目录。顺序很关键：目标目录可能位于源目录
            # 内部，若先 rename(source) 会把归档一起搬走，随后解压直接报"文件
            # 不存在"。同时这也让解压失败时源目录保持原样、无需回滚。
            staging = entry if os.path.isdir(entry) else None
            created_staging = staging is None
            old = None
            try:
                if created_staging:
                    staging = tempfile.mkdtemp(prefix="backupapp_restore_")
                    compress.extract_archive(entry, staging, plan.password)
                if linkmod.is_link(source):
                    linkmod.remove_link(source)
                if os.path.exists(source):
                    old = f"{source}.{datetime.now().strftime('%Y%m%d_%H%M%S')}.old"
                    os.rename(source, old)
                    logging.get_logger().info(
                        _("restore: 原目录改名保护 -> %s"), old)
                os.makedirs(source, exist_ok=True)
                items = [os.path.join(staging, i) for i in sorted(os.listdir(staging))]
                # 归档/快照目录以单个根目录形态保存（copy/link 模式皆然）：
                # 顶层只有一个目录时解开一层，内容直接落入 source
                if len(items) == 1 and os.path.isdir(items[0]):
                    items = [os.path.join(items[0], i)
                             for i in sorted(os.listdir(items[0]))]
                for it in items:
                    # 拷贝而非移动：文件夹快照可重复恢复
                    if os.path.isdir(it):
                        shutil.copytree(it, os.path.join(source, os.path.basename(it)),
                                        dirs_exist_ok=True)
                    else:
                        shutil.copy2(it, os.path.join(source, os.path.basename(it)))
            except BaseException:
                # 失败回滚：清掉半成品 source，把 .old 还原回原位，
                # 否则用户的数据只剩在 .old 目录里、source 成了残缺目录
                if old is not None:
                    shutil.rmtree(source, ignore_errors=True)
                    try:
                        os.rename(old, source)
                        logging.get_logger().warning(
                            _("restore: 失败已回滚，原目录还原 -> %s"), source)
                    except OSError as e:
                        logging.get_logger().error(
                            _("restore: 回滚失败，数据保留在 %s: %s"), old, e)
                raise
            finally:
                # 临时解压目录无论成败都要清理（失败路径原先会整份残留）
                if created_staging and staging:
                    shutil.rmtree(staging, ignore_errors=True)

        plan.last_result = "restored"
        plan.updated_at = datetime.now().isoformat(timespec="seconds")
        store.save_app(app)
        _prune_old_siblings(source)
        logging.get_logger().info("restore ok %s <- %s", plan_key, entry)
        return RestoreResult(True, plan_key, retention.snapshot_of(entry), source)
    except Exception as e:
        logging.get_logger().error("restore failed %s: %s", plan_key, e)
        return RestoreResult(False, plan_key, error=str(e))
