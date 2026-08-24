"""备份引擎：run_plan / run_all。link 模式与保留策略在此编排。"""

import os
import time
from dataclasses import dataclass, field
from datetime import datetime

from .. import logging
from ..storage import store
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


def run_plan(plan_key: str, progress=None) -> BackupResult:
    """执行单个计划备份；progress(msg) 可选，每文件回调一次（供 GUI 实时显示）。"""
    start = time.time()
    try:
        pair = store.load_plan(*plan_key.split("/", 1))
        if not pair:
            raise ValueError(f"计划不存在: {plan_key}")
        app, plan = pair
        if not plan.sources:
            raise ValueError(f"计划 {plan_key} 没有配置源路径")
        dest = paths.expand(plan.destination)
        os.makedirs(dest, exist_ok=True)
        srcs = paths.expand_many(plan.sources)

        if plan.backup_mode == "link":
            live_dir = linkmod.live_dir_for(dest, app.id)
            linkmod.ensure_linked(srcs[0], live_dir, plan.link_type)
            srcs = [live_dir] + srcs[1:]

        # 前置钩子：失败（非零/超时）则中止备份
        hooks.run_hook(plan.pre_cmd, plan.cmd_timeout, plan_key, "备份前")

        snapshot = datetime.now().strftime("%Y%m%d_%H%M%S")
        entry = retention.entry_path(dest, app.id, snapshot, plan.compress, plan.format)
        p = _mk_progress(plan_key, progress)
        if plan.compress:
            files, size = compress.create_archive(srcs, entry, plan.format,
                                                  plan.password, plan.exclude,
                                                  progress=p)
        else:
            files, size = compress.copy_tree(srcs, entry, plan.exclude, progress=p)
        pruned = retention.prune(dest, app.id, plan.retention, plan.keep_monthly,
                                 plan.keep_yearly, plan.retention_unit)

        # 后置钩子：失败仅记录日志，不影响备份结果
        try:
            hooks.run_hook(plan.post_cmd, plan.cmd_timeout, plan_key, "备份后")
        except RuntimeError as e:
            logging.get_logger().warning("[%s] 备份后钩子失败: %s", plan_key, e)

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
    results = []
    for app in store.list_apps():
        for plan in app.plans:
            if not plan.enabled:
                continue
            results.append(run_plan(f"{app.id}/{plan.id}", progress=progress))
    return results


def run_app(app_id: str, progress=None) -> list[BackupResult]:
    app = store.load_app(app_id)
    if not app:
        raise ValueError(f"应用不存在: {app_id}")
    return [run_plan(f"{app.id}/{p.id}", progress=progress)
            for p in app.plans if p.enabled]
