"""QThread workers：备份/恢复/自身备份在后台线程执行，不冻结界面。

worker 内统一加文件锁，防止与系统计划任务的备份进程并发。
"""

from PySide6.QtCore import QThread, Signal

from ..storage import lock


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
            self._emit_error(f"异常: {e}")
            return
        if not isinstance(out, (list, tuple)):
            out = [out]
        ok_n = 0
        for r in out:
            ok = bool(getattr(r, "ok", False))
            ok_n += int(ok)
            if ok:
                msg = f"{getattr(r, 'files', 0)} 文件 / {getattr(r, 'bytes', 0)} 字节"
                if getattr(r, "pruned", 0):
                    msg += f" / 清理 {getattr(r, 'pruned', 0)} 个旧备份"
            else:
                msg = f"失败: {getattr(r, 'error', '未知错误')}"
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
            self.result.emit("-", False, f"异常: {e}")
            self.finished_all.emit(0, 1)
            return
        if not isinstance(out, (list, tuple)):
            out = [out]
        ok_n = 0
        for r in out:
            ok = bool(getattr(r, "ok", False))
            ok_n += int(ok)
            if ok:
                msg = f"快照 {getattr(r, 'snapshot', '')} -> {getattr(r, 'target', '')}"
            else:
                msg = f"失败: {getattr(r, 'error', '未知错误')}"
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
                                 "已注册" if self._register else "已取消注册")
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
        try:
            ok, msg = make_uploader(plain_sb(self._sb)).test()
        except Exception as e:
            ok, msg = False, str(e)
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
            self.done.emit(True, f"已恢复 {r.files} 个文件")
        else:
            self.done.emit(False, r.error or "恢复失败")


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
        self.done.emit(err is None, err or "已删除")
