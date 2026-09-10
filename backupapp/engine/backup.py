"""备份引擎：run_plan / run_all。link 模式与保留策略在此编排。"""

import os
import time
from dataclasses import dataclass, field
from datetime import datetime

from .. import logging
from ..i18n import _
from ..storage import lock, store
from ..util import format_size
from . import compress, hooks, link as linkmod, paths, retention


@dataclass
class BackupResult:
    ok: bool
    plan_key: str
    snapshot: str = ""
    archive_path: str = ""
    files: int = 0
    bytes: int = 0
    duration_s: float = 0.0
    error: str | None = None
    pruned: int = 0


def _mk_progress(plan_key: str, cb):
    """把压缩层的 (arc, i, total) 进度包装成带 plan_key 的消息回调。"""
    if cb is None:
        return None

    def _p(arc: str, i: int, total: int):
        cb(f"{plan_key} [{i}/{total}] {arc}")
    return _p


def _self_inclusion_skips(srcs: list[str], dest: str, entry: str,
                          plan_key: str) -> list[str]:
    """计算打包时要跳过的路径，避免归档把自己读进去。

    目标目录在源目录内时，历史备份会被再次打包进新备份，体积逐份翻倍。
    因此默认把整个目标目录排除；但若某个源本身就在目标目录内（link 模式的
    live/<app> 目录正是这种情况），就只能排除本次写入的条目，否则会把真正
    要备份的数据一起排掉。
    """
    skip = [entry, entry + ".part"]
    source_inside_dest = any(compress.is_within(s, dest) for s in srcs)
    if source_inside_dest:
        return skip
    if any(compress.is_within(dest, s) for s in srcs):
        logging.get_logger().warning(
            _("[%s] 目标目录位于源目录内（%s），已自动排除目标目录本身以避免"
              "备份自我包含"), plan_key, dest)
        skip.append(dest)
    return skip


def run_plan(plan_key: str, progress=None) -> BackupResult:
    """执行单个计划备份；progress(msg) 可选，每文件回调一次（供 GUI 实时显示）。

    加 DataLock：计划任务调用 CLI（backupapp backup）时不经过 GUI worker，
    若不在此加锁会与手动备份并发写 apps/*.json 造成丢更新。DataLock 同线程
    可重入，GUI worker 已持锁时这里的嵌套获取是空操作。
    """
    start = time.time()
    try:
        with lock.DataLock(lock.lock_path()):
            return _run_plan_locked(plan_key, progress, start)
    except RuntimeError as e:
        # 锁被其他进程占用：按失败结果返回，不抛给调用方
        logging.get_logger().warning("backup skipped %s: %s", plan_key, e)
        return BackupResult(False, plan_key, error=str(e),
                            duration_s=time.time() - start)
    except Exception as e:
        logging.get_logger().error("backup failed %s: %s", plan_key, e)
        return BackupResult(False, plan_key, error=str(e),
                            duration_s=time.time() - start)


def _run_plan_locked(plan_key: str, progress, start: float) -> BackupResult:
    try:
        pair = store.load_plan(*plan_key.split("/", 1))
        if not pair:
            raise ValueError(_("计划不存在: {plan_key}").format(plan_key=plan_key))
        app, plan = pair
        if not plan.sources:
            raise ValueError(
                _("计划 {plan_key} 没有配置源路径").format(plan_key=plan_key))
        dest = paths.expand(plan.destination)
        os.makedirs(dest, exist_ok=True)
        srcs = paths.expand_many(plan.sources)

        if plan.backup_mode == "link":
            live_dir = linkmod.live_dir_for(dest, app.id)
            linkmod.ensure_linked(srcs[0], live_dir, plan.link_type)
            srcs = [live_dir] + srcs[1:]

        # 前置钩子：失败（非零/超时）则中止备份
        hooks.run_hook(plan.pre_cmd, plan.cmd_timeout, plan_key, _("备份前"))

        snapshot = datetime.now().strftime("%Y%m%d_%H%M%S")
        # 同一秒内重复备份会算出同名条目并互相覆盖：冲突时逐秒前移
        snapshot = retention.unique_snapshot(dest, app.id, snapshot)
        entry = retention.entry_path(dest, app.id, snapshot, plan.compress, plan.format)
        skip = _self_inclusion_skips(srcs, dest, entry, plan_key)
        p = _mk_progress(plan_key, progress)
        if plan.compress:
            files, size = compress.create_archive(srcs, entry, plan.format,
                                                  plan.password, plan.exclude,
                                                  progress=p, skip_paths=skip)
        else:
            files, size = compress.copy_tree(srcs, entry, plan.exclude,
                                             progress=p, skip_paths=skip)
        pruned = retention.prune(dest, app.id, plan.retention, plan.keep_monthly,
                                 plan.keep_yearly, plan.retention_unit)

        # 后置钩子：失败仅记录日志，不影响备份结果
        try:
            hooks.run_hook(plan.post_cmd, plan.cmd_timeout, plan_key, _("备份后"))
        except RuntimeError as e:
            logging.get_logger().warning(_("[%s] 备份后钩子失败: %s"), plan_key, e)

        plan.last_run_at = datetime.now().isoformat(timespec="seconds")
        plan.updated_at = plan.last_run_at
        plan.last_result = "ok"
        store.save_app(app)
        logging.get_logger().info(
            "backup ok %s -> %s (%d files, %s, pruned %d)",
            plan_key, entry, files, format_size(size), pruned)
        return BackupResult(True, plan_key, snapshot, entry, files, size,
                            time.time() - start, None, pruned)
    except Exception as e:
        logging.get_logger().error("backup failed %s: %s", plan_key, e)
        try:
            app, plan = store.load_plan(*plan_key.split("/", 1))
            if app and plan:
                plan.last_run_at = datetime.now().isoformat(timespec="seconds")
                plan.updated_at = plan.last_run_at
                plan.last_result = f"error: {e}"
                store.save_app(app)
        except Exception:
            pass
        return BackupResult(False, plan_key, error=str(e),
                            duration_s=time.time() - start)


def run_all(progress=None) -> list[BackupResult]:
    """跑所有启用计划。整批持锁（同线程重入），避免与其他进程的备份交错。"""
    results = []
    with lock.DataLock(lock.lock_path()):
        for app in store.list_apps():
            for plan in app.plans:
                if not plan.enabled:
                    continue
                results.append(run_plan(f"{app.id}/{plan.id}", progress=progress))
    return results


def run_app(app_id: str, progress=None) -> list[BackupResult]:
    app = store.load_app(app_id)
    if not app:
        raise ValueError(_("应用不存在: {app_id}").format(app_id=app_id))
    with lock.DataLock(lock.lock_path()):
        return [run_plan(f"{app.id}/{p.id}", progress=progress)
                for p in app.plans if p.enabled]
