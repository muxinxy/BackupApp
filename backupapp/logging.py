"""日志：data/logs/backup.log，按大小轮转。"""

import logging
import os
from logging.handlers import RotatingFileHandler

from .storage import store

_logger: logging.Logger | None = None


def get_logger() -> logging.Logger:
    global _logger
    if _logger is None:
        _logger = logging.getLogger("backupapp")
        _logger.setLevel(logging.INFO)
        fh = RotatingFileHandler(
            os.path.join(store.logs_dir(), "backup.log"),
            maxBytes=5 * 1024 * 1024, backupCount=2, encoding="utf-8")
        fh.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
        _logger.addHandler(fh)
        sh = logging.StreamHandler()
        sh.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
        _logger.addHandler(sh)
    return _logger
