"""QThread workers：备份/恢复/自身备份在后台线程执行，不冻结界面。

worker 内统一加文件锁，防止与系统计划任务的备份进程并发。
"""

from PySide6.QtCore import QThread, Signal

from ..i18n import _
from ..storage import lock
from ..util import format_size


class BackupWorker(QThread):
    result = Signal(str, bool, str)  # plan_key, ok, 详情
    finished_all = Signal(int, int)  # 成功数, 总数
    progress = Signal(str)           # 备份进度行（后台节流后发主线程日志）

    def __init__(self, fn, parent=None):
        super().__init__(parent)
        self._fn = fn

    def _emit_error(self, msg: str):
        self.result.emit("-", False, msg)
        self.finished_all.emit(0, 1)

    def run(self):
        import time
        _last = [0.0]

        def _progress(msg: str):
            # 节流：最快每 150ms 一条，避免大目录刷爆日志
            now = time.monotonic()
            if now - _last[0] < 0.15:
                return
            _last[0] = now
            self.progress.emit(msg)

        try:
            with lock.DataLock(lock.lock_path()):
                out = self._fn(_progress)
        except RuntimeError as e:  # 锁被占用
            self._emit_error(str(e))
            return
        except Exception as e:
            self._emit_error(_("异常: {e}").format(e=e))
            return
        if not isinstance(out, (list, tuple)):
            out = [out]
        ok_n = 0
        for r in out:
            ok = bool(getattr(r, "ok", False))
            ok_n += int(ok)
            if ok:
                msg = _("{n} 文件 / {size}").format(
                    n=getattr(r, "files", 0),
                    size=format_size(getattr(r, "bytes", 0)))
                if getattr(r, "pruned", 0):
                    msg += _(" / 清理 {n} 个旧备份").format(
                        n=getattr(r, "pruned", 0))
            else:
                msg = _("失败: {err}").format(
                    err=getattr(r, "error", _("未知错误")))
            self.result.emit(getattr(r, "plan_key", "-"), ok, msg)
        self.finished_all.emit(ok_n, len(out))


class RestoreWorker(QThread):
    result = Signal(str, bool, str)
    finished_all = Signal(int, int)

    def __init__(self, fn, parent=None):
        super().__init__(parent)
        self._fn = fn

    def run(self):
        try:
            with lock.DataLock(lock.lock_path()):
                out = self._fn()
        except Exception as e:
            self.result.emit("-", False, _("异常: {e}").format(e=e))
            self.finished_all.emit(0, 1)
            return
        if not isinstance(out, (list, tuple)):
            out = [out]
        ok_n = 0
        for r in out:
            ok = bool(getattr(r, "ok", False))
            ok_n += int(ok)
            if ok:
                msg = _("快照 {snap} -> {target}").format(
                    snap=getattr(r, "snapshot", ""),
                    target=getattr(r, "target", ""))
            else:
                msg = _("失败: {err}").format(
                    err=getattr(r, "error", _("未知错误")))
            self.result.emit(getattr(r, "plan_key", "-"), ok, msg)
        self.finished_all.emit(ok_n, len(out))


class BatchTaskWorker(QThread):
    """批量注册/取消计划任务（后台逐条调 schtasks，不冻结界面）。"""

    result = Signal(str, bool, str)  # plan_key, ok, 详情
    finished_all = Signal(int, int)  # 成功数, 尝试总数

    def __init__(self, register: bool, parent=None):
        super().__init__(parent)
        self._register = register

    def run(self):
        from .. import scheduler as sched
        from ..storage import store
        cfg = store.load_settings()
        plans = [(a.id, p) for a in store.list_apps() for p in a.plans if p.enabled]
        reg = sched.registered_plan_tasks()
        ok = total = 0
        for app_id, p in plans:
            name = sched.plan_task_name(app_id, p.id)
            if self._register:
                if name in reg:
                    continue
                err = sched.plan_install(cfg, app_id, p.id)
            else:
                if name not in reg:
                    continue
                err = sched.plan_uninstall(app_id, p.id)
            total += 1
            if err:
                self.result.emit(f"{app_id}/{p.id}", False, err)
            else:
                ok += 1
                self.result.emit(f"{app_id}/{p.id}", True,
                                 _("已注册") if self._register else _("已取消注册"))
        self.finished_all.emit(ok, total)


class JobWorker(QThread):
    """在后台执行一个可调用对象，返回 (ok, payload, 描述)。

    fn() 可返回 payload，或返回 (payload, 描述文本)；payload 交给主线程的
    完成回调收尾。用于导入/导出这类可能涉及大 zip 读写与解密的操作——这些
    都不该在 UI 线程同步执行（大文件会明显卡界面）。
    """

    done = Signal(bool, object, str)  # ok, payload, 描述/错误

    def __init__(self, fn, parent=None):
        super().__init__(parent)
        self._fn = fn

    def run(self):
        try:
            result = self._fn()
        except Exception as e:
            self.done.emit(False, None, str(e))
            return
        if isinstance(result, tuple) and len(result) == 2:
            payload, detail = result
        else:
            payload, detail = result, ""
        self.done.emit(True, payload, "" if detail is None else str(detail))


class TaskOpWorker(QThread):
    """后台执行单条/多条计划任务的注册与取消注册。

    schtasks 子进程冷缓存时单次可达数秒（_run 超时 20s），在 UI 线程直接调用会
    冻结界面。所有 install/uninstall 调用点（单条切换、编辑后重注册、删除计划、
    删除应用、全局任务）统一走这里。
    """

    result = Signal(str, bool, str)  # plan_key, ok, 详情
    finished_all = Signal(int, int)  # 成功数, 尝试总数

    def __init__(self, ops, parent=None):
        """ops: [(op, app_id, plan_id)]，op 为 "install" | "uninstall"。

        全局任务用 op "global_install" / "global_uninstall"（忽略 app_id/plan_id）。
        """
        super().__init__(parent)
        self._ops = list(ops)

    def run(self):
        from .. import scheduler as sched
        from ..storage import store
        cfg = store.load_settings()
        ok = total = 0
        for op, app_id, plan_id in self._ops:
            total += 1
            key = f"{app_id}/{plan_id}" if app_id else op
            try:
                if op == "install":
                    err = sched.plan_install(cfg, app_id, plan_id)
                elif op == "uninstall":
                    err = sched.plan_uninstall(app_id, plan_id)
                elif op == "global_install":
                    err = sched.install(cfg)
                elif op == "global_uninstall":
                    err = sched.uninstall(cfg)
                else:
                    err = _("未知操作: {op}").format(op=op)
            except Exception as e:
                err = str(e)
            if err:
                self.result.emit(key, False, err)
            else:
                ok += 1
                msg = {"install": _("已注册"), "global_install": _("已注册"),
                       "uninstall": _("已取消注册"),
                       "global_uninstall": _("已取消注册")}.get(op, "")
                self.result.emit(key, True, msg)
        self.finished_all.emit(ok, total)


class TestWorker(QThread):
    """协议连通性测试。"""

    done = Signal(bool, str)

    def __init__(self, sb, parent=None):
        super().__init__(parent)
        self._sb = sb

    def run(self):
        from ..protocols.base import make_uploader
        from ..security import plain_sb
        u = None
        try:
            u = make_uploader(plain_sb(self._sb))
            ok, msg = u.test()
        except Exception as e:
            ok, msg = False, str(e)
        finally:
            if u is not None:
                u.close()
        self.done.emit(ok, msg)


class SelfListWorker(QThread):
    """后台加载远程自身备份文件列表。"""

    done = Signal(object, str)  # list[RemoteFile] | None, 错误信息

    def __init__(self, protocol: str, parent=None):
        super().__init__(parent)
        self._protocol = protocol

    def run(self):
        from ..protocols.runner import list_remote_files
        try:
            self.done.emit(list_remote_files(self._protocol), "")
        except Exception as e:
            self.done.emit(None, str(e))


class SelfRestoreWorker(QThread):
    """后台执行自身备份恢复。"""

    done = Signal(bool, str)

    def __init__(self, protocol: str, remote_name: str, overwrite: bool = True,
                 parent=None):
        super().__init__(parent)
        self._protocol = protocol
        self._remote_name = remote_name
        self._overwrite = overwrite

    def run(self):
        from ..protocols.runner import run_self_restore
        r = run_self_restore(self._protocol, self._remote_name,
                             overwrite=self._overwrite)
        if r.ok:
            self.done.emit(True, _("已恢复 {n} 个文件").format(n=r.files))
        else:
            self.done.emit(False, r.error or _("恢复失败"))


class SelfDeleteWorker(QThread):
    """后台删除远程自身备份文件。"""

    done = Signal(bool, str)

    def __init__(self, protocol: str, remote_name: str, parent=None):
        super().__init__(parent)
        self._protocol = protocol
        self._remote_name = remote_name

    def run(self):
        from ..protocols.runner import delete_remote_file
        err = delete_remote_file(self._protocol, self._remote_name)
        self.done.emit(err is None, err or _("已删除"))


class SchedRefreshWorker(QThread):
    """后台查询系统计划任务注册状态，避免主线程冻结。

    schtasks /query /v 冷缓存时可达数秒；注册任务集与全局状态共用一次查询
    （scheduler 内部 5 秒 TTL）。done 的两个参数在查询失败时为 None。
    """

    done = Signal(object, object)  # registered: set|None, global_status: str|None

    def __init__(self, cfg, parent=None):
        super().__init__(parent)
        self._cfg = cfg

    def run(self):
        from .. import scheduler as sched
        try:
            registered = sched.registered_plan_tasks()
        except Exception:
            registered = None
        try:
            st = sched.status(self._cfg)
        except Exception:
            st = None
        self.done.emit(registered, st)
