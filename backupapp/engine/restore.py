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
from ..storage import store
from . import compress, link as linkmod, paths, retention


@dataclass
class RestoreResult:
    ok: bool
    plan_key: str
    snapshot: str = ""
    target: str = ""
    error: str | None = None


def restore_plan(plan_key: str, snapshot: str | None = None) -> RestoreResult:
    try:
        pair = store.load_plan(*plan_key.split("/", 1))
        if not pair:
            raise ValueError(f"计划不存在: {plan_key}")
        app, plan = pair
        if not plan.sources:
            raise ValueError(f"计划 {plan_key} 没有配置源路径")
        source = paths.expand(plan.sources[0])
        dest = paths.expand(plan.destination)
        live_dir = linkmod.live_dir_for(dest, app.id)

        entries = retention.list_entries(dest, app.id)
        if not entries:
            raise ValueError(f"{dest} 下没有 {app.id} 的备份")
        entry = next((e for e in entries if not snapshot or snapshot in e), entries[0])
        if snapshot and not (snapshot in entry):
            raise ValueError(f"找不到快照 {snapshot}，可用: {[retention.snapshot_of(e) for e in entries]}")

        if plan.restore_mode == "link":
            if linkmod.is_link(source):
                pass  # 已就位
            elif not os.path.exists(live_dir):
                linkmod.ensure_linked(source, live_dir, plan.link_type)
            else:
                raise ValueError(
                    f"live 目录 {live_dir} 已存在且 {source} 是真实目录，请手动处理")
        else:
            if linkmod.is_link(source):
                linkmod.remove_link(source)
            if os.path.exists(source):
                old = f"{source}.{datetime.now().strftime('%Y%m%d_%H%M%S')}.old"
                os.rename(source, old)
                logging.get_logger().info("restore: 原目录改名保护 -> %s", old)
            os.makedirs(source, exist_ok=True)
            staging = entry if os.path.isdir(entry) else None
            if staging is None:
                staging = tempfile.mkdtemp(prefix="backupapp_restore_")
                compress.extract_archive(entry, staging, plan.password)
            items = [os.path.join(staging, i) for i in sorted(os.listdir(staging))]
            # 归档/快照目录以单个根目录形态保存（copy/link 模式皆然）：
            # 顶层只有一个目录时解开一层，内容直接落入 source
            if len(items) == 1 and os.path.isdir(items[0]):
                items = [os.path.join(items[0], i) for i in sorted(os.listdir(items[0]))]
            for it in items:
                # 拷贝而非移动：文件夹快照可重复恢复
                if os.path.isdir(it):
                    shutil.copytree(it, os.path.join(source, os.path.basename(it)),
                                    dirs_exist_ok=True)
                else:
                    shutil.copy2(it, os.path.join(source, os.path.basename(it)))
            if staging != entry:
                shutil.rmtree(staging, ignore_errors=True)

        plan.last_result = "restored"
        plan.updated_at = datetime.now().isoformat(timespec="seconds")
        store.save_app(app)
        logging.get_logger().info("restore ok %s <- %s", plan_key, entry)
        return RestoreResult(True, plan_key, retention.snapshot_of(entry), source)
    except Exception as e:
        logging.get_logger().error("restore failed %s: %s", plan_key, e)
        return RestoreResult(False, plan_key, error=str(e))
