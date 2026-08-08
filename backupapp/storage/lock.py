"""跨平台文件锁：防止计划任务与手动备份并发执行。"""

import os
import sys


class DataLock:
    """以 data/.lock 为锁文件，非阻塞获取，获取失败抛异常。"""

    def __init__(self, lock_path: str):
        self._path = lock_path
        self._fh = None

    def __enter__(self) -> "DataLock":
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
            raise RuntimeError(f"另一个备份进程正在运行（锁文件 {self._path}）") from e
        return self

    def __exit__(self, *exc) -> None:
        if self._fh:
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
