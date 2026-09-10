"""跨平台文件锁：防止计划任务与手动备份并发执行。"""

import os
import sys
import threading

from ..i18n import _

# 同一线程内的嵌套获取视为重入（GUI worker 已持锁，引擎入口再取一次不应失败）。
# key = 锁文件路径 -> (持有线程 id, 嵌套深度)；跨线程/跨进程仍由 OS 锁仲裁。
_state: dict[str, tuple[int, int]] = {}
_state_guard = threading.Lock()


class DataLock:
    """以 data/.lock 为锁文件，非阻塞获取，获取失败抛异常。

    可重入：同一线程重复进入只增加计数，最外层退出时才真正释放。
    """

    def __init__(self, lock_path: str):
        self._path = lock_path
        self._fh = None
        self._nested = False

    def __enter__(self) -> "DataLock":
        tid = threading.get_ident()
        with _state_guard:
            held = _state.get(self._path)
            if held and held[0] == tid:
                _state[self._path] = (tid, held[1] + 1)
                self._nested = True
                return self
        self._fh = open(self._path, "a+")
        try:
            if sys.platform == "win32":
                import msvcrt
                msvcrt.locking(self._fh.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(self._fh.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as e:
            self._fh.close()
            self._fh = None
            raise RuntimeError(
                _("另一个备份进程正在运行（锁文件 {path}）").format(path=self._path)
            ) from e
        with _state_guard:
            _state[self._path] = (tid, 1)
        return self

    def __exit__(self, *exc) -> None:
        if self._nested:
            tid = threading.get_ident()
            with _state_guard:
                held = _state.get(self._path)
                if held and held[0] == tid:
                    if held[1] <= 1:
                        _state.pop(self._path, None)
                    else:
                        _state[self._path] = (tid, held[1] - 1)
            return
        if self._fh:
            tid = threading.get_ident()
            with _state_guard:
                held = _state.get(self._path)
                if held and held[0] == tid:
                    _state.pop(self._path, None)
            try:
                if sys.platform == "win32":
                    import msvcrt
                    self._fh.seek(0)
                    msvcrt.locking(self._fh.fileno(), msvcrt.LK_UNLCK, 1)
                else:
                    import fcntl
                    fcntl.flock(self._fh.fileno(), fcntl.LOCK_UN)
            finally:
                self._fh.close()
                self._fh = None


def lock_path() -> str:
    from . import store
    return os.path.join(store.data_dir(), ".lock")
