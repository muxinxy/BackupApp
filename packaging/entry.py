"""PyInstaller 入口：以真实包导入方式启动，保证相对导入与包数据完整。"""

import sys

from backupapp.__main__ import main

if __name__ == "__main__":
    sys.exit(main())
