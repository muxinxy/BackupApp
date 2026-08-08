"""通用组件：路径列表编辑器（目录/文件浏览 + 逐行删除 + 变量化）。"""

import os

from PySide6.QtCore import QSize, Qt
from PySide6.QtWidgets import (QFileDialog, QHBoxLayout, QLabel, QListWidget,
                               QListWidgetItem, QPushButton, QVBoxLayout, QWidget)

from ..engine.paths import compact


class PathListEditor(QWidget):
    """可增删的路径列表：每行一个路径 + 删除按钮，支持浏览目录/文件。

    添加的绝对路径会自动替换为 %VAR%/~/ 变量形式（跨机器可移植）。
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self._list = QListWidget()
        self._list.setSelectionMode(QListWidget.SingleSelection)
        # 行内 itemWidget 自带边距，屏蔽全局 QListWidget::item padding 防裁切
        self._list.setStyleSheet(
            "QListWidget::item { padding: 0px; margin: 0px; }")
        row = QHBoxLayout()
        row.setContentsMargins(0, 0, 0, 0)
        btn_dir = QPushButton("添加目录")
        btn_file = QPushButton("添加文件")
        btn_del = QPushButton("删除选中")
        btn_dir.clicked.connect(self._add_dir)
        btn_file.clicked.connect(self._add_file)
        btn_del.clicked.connect(self._remove_selected)
        row.addWidget(btn_dir)
        row.addWidget(btn_file)
        row.addWidget(btn_del)
        row.addStretch(1)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.addWidget(self._list, 1)
        lay.addLayout(row)

    # ---- 增 ----

    def _add_dir(self):
        p = QFileDialog.getExistingDirectory(self, "选择目录")
        if p:
            self.add_path(p)

    def _add_file(self):
        p, _ = QFileDialog.getOpenFileName(self, "选择文件")
        if p:
            self.add_path(p)

    def add_path(self, p: str):
        p = compact(p)
        if p in self.paths():
            return
        item = QListWidgetItem()
        item.setData(Qt.UserRole, p)
        self._list.addItem(item)
        w = QWidget()
        lay = QHBoxLayout(w)
        lay.setContentsMargins(4, 2, 4, 2)
        lay.setSpacing(6)
        lbl = QLabel(p)
        lbl.setStyleSheet("border: none; background: transparent;")
        btn = QPushButton("✕")
        btn.setFixedSize(22, 22)
        btn.setToolTip("删除该路径")
        btn.setStyleSheet(
            "QPushButton { padding: 0; border-radius: 11px; background: #eef1f6; }"
            "QPushButton:hover { background: #fde8e8; color: #b91c1c; }")
        btn.clicked.connect(
            lambda _checked, it=item: self._list.takeItem(self._list.row(it)))
        lay.addWidget(lbl, 1)
        lay.addWidget(btn)
        w.adjustSize()
        item.setSizeHint(QSize(max(240, w.sizeHint().width()),
                               max(30, w.sizeHint().height())))
        self._list.setItemWidget(item, w)

    # ---- 删 ----

    def _remove_selected(self):
        for item in self._list.selectedItems():
            self._list.takeItem(self._list.row(item))

    # ---- 查/置 ----

    def paths(self) -> list[str]:
        return [self._list.item(i).data(Qt.UserRole)
                for i in range(self._list.count())]

    def set_paths(self, paths: list[str]):
        self._list.clear()
        for p in paths:
            self.add_path(p)

    def add_preset_path(self, p: str):
        """从应用配置路径添加（去重后追加）。"""
        p = p.strip()
        if p:
            self.add_path(p)
