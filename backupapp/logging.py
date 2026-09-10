"""日志：data/logs/backup.log，按大小轮转。"""

import logging
import os
from logging.handlers import RotatingFileHandler

from .storage import store

_logger: logging.Logger | None = None

_LEVELS = {"debug": logging.DEBUG, "info": logging.INFO,
           "warning": logging.WARNING, "error": logging.ERROR}


def get_logger() -> logging.Logger:
    global _logger
    if _logger is None:
        _logger = logging.getLogger("backupapp")
        _configure(_logger)
    return _logger


def _configure(logger: logging.Logger) -> None:
    """按 General 设置配置级别与轮转大小（读不到设置时用默认值）。

    maxBytes 设 0 在 RotatingFileHandler 表示不轮转，这里为避免用户误配导致
    日志无限增长，最小按 1MB 处理。
    """
    level_name, max_mb = "info", 5
    try:
        general = store.load_settings().general
        level_name = (general.log_level or "info").lower()
        max_mb = int(general.max_log_size_mb or 5)
    except Exception:
        pass  # 设置不可读时保持默认，日志模块自身不能因此失效
    logger.setLevel(_LEVELS.get(level_name, logging.INFO))
    max_bytes = max(1, max_mb) * 1024 * 1024
    fh = RotatingFileHandler(
        os.path.join(store.logs_dir(), "backup.log"),
        maxBytes=max_bytes, backupCount=2, encoding="utf-8")
    fh.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
    logger.addHandler(fh)
    sh = logging.StreamHandler()
    sh.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
    logger.addHandler(sh)
