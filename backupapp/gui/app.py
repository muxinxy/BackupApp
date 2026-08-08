"""GUI 入口：backupapp gui / python -m backupapp.gui.app / 双击 exe。"""

import os
import sys

from PySide6.QtWidgets import QApplication

from ..storage import store


def _portable_root() -> str:
    if getattr(sys, "frozen", False):
        return os.path.join(os.path.dirname(sys.executable), "data")
    return os.path.join(os.getcwd(), "data")


def main() -> int:
    argv = sys.argv
    data_dir = None
    for i, a in enumerate(argv):
        if a == "--data-dir" and i + 1 < len(argv):
            data_dir = argv[i + 1]
    store.set_data_root(data_dir or _portable_root())
    app = QApplication(argv)
    from . import theme
    theme.apply_theme(app, store.load_settings().general.theme)
    from .main_window import MainWindow
    w = MainWindow()
    w.show()
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
