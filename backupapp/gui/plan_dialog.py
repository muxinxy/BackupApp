"""备份计划新增/编辑对话框。"""

import os
from datetime import datetime

from PySide6.QtWidgets import (QCheckBox, QComboBox, QDialog, QDialogButtonBox,
                               QFileDialog, QFormLayout, QHBoxLayout, QLabel,
                               QLineEdit, QMessageBox, QPlainTextEdit, QPushButton,
                               QSpinBox, QVBoxLayout)

from ..engine.paths import compact
from ..model import AppConfig, BackupPlan, now_iso
from .widgets import PathListEditor


class PlanDialog(QDialog):
    def __init__(self, app: AppConfig, plan: BackupPlan | None = None, parent=None):
        super().__init__(parent)
        self.setWindowTitle("编辑备份计划" if plan else "新增备份计划")
        self.setMinimumWidth(520)
        self._app = app
        self._plan = plan

        default_id = plan.id if plan else \
            f"{app.id}_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
        self._id = QLineEdit(default_id)
        self._name = QLineEdit(plan.name if plan else default_id)
        # 名称默认跟随 ID（仅在名称为空时同步）
        if plan is None:
            self._id.textChanged.connect(
                lambda t: self._name.setText(t) if not self._name.text() else None)
        self._sources = PathListEditor()
        self._sources.set_paths(plan.sources if plan else [])
        self._destination = QLineEdit(plan.destination if plan else "")
        dest_btn = QPushButton("浏览")
        dest_btn.clicked.connect(self._browse_dest)
        dest_row = QHBoxLayout()
        dest_row.addWidget(self._destination, 1)
        dest_row.addWidget(dest_btn)

        # 从应用配置路径添加预设
        presets = list(dict.fromkeys(app.config_paths + app.data_paths))
        preset_row = QHBoxLayout()
        self._preset_combo = QComboBox()
        self._preset_combo.addItems(presets)
        btn_preset = QPushButton("添加预设")
        btn_preset.clicked.connect(
            lambda: self._sources.add_preset_path(self._preset_combo.currentText()))
        preset_row.addWidget(QLabel("应用路径:"))
        preset_row.addWidget(self._preset_combo, 1)
        preset_row.addWidget(btn_preset)

        self._retention = QSpinBox()
        self._retention.setRange(1, 9999)
        self._retention.setValue(plan.retention if plan else 14)
        self._keep_monthly = QCheckBox("额外保留每月第一份")
        self._keep_monthly.setChecked(plan.keep_monthly if plan else True)
        self._compress = QCheckBox("压缩备份")
        self._compress.setChecked(plan.compress if plan else True)
        self._format = QComboBox()
        self._format.addItems(["zip", "7z", "tar.gz"])
        self._format.setCurrentText(plan.format if plan else "zip")
        self._password = QLineEdit(plan.password if plan else "")
        self._password.setEchoMode(QLineEdit.Password)
        self._password.setPlaceholderText("zip 使用 AES 加密；tar.gz 不支持密码")
        self._exclude = QPlainTextEdit("\n".join(plan.exclude) if plan else "")
        self._exclude.setPlaceholderText("每行一个排除规则（通配符），如 cache、*.log")
        self._backup_mode = QComboBox()
        self._backup_mode.addItem("原样复制", "copy")
        self._backup_mode.addItem("替换为链接（数据存备份目录）", "link")
        self._backup_mode.setCurrentIndex(0 if (plan is None or plan.backup_mode == "copy") else 1)
        self._restore_mode = QComboBox()
        self._restore_mode.addItem("原样复制回源路径", "copy")
        self._restore_mode.addItem("替换为链接（不拷贝）", "link")
        self._restore_mode.setCurrentIndex(0 if (plan is None or plan.restore_mode == "copy") else 1)
        self._link_type = QComboBox()
        self._link_type.addItem("junction（免管理员，推荐）", "junction")
        self._link_type.addItem("symlink（需管理员/开发者模式）", "symlink")
        self._link_type.setCurrentIndex(0 if (plan is None or plan.link_type == "junction") else 1)

        form = QFormLayout()
        form.addRow("ID", self._id)
        form.addRow("名称", self._name)
        form.addRow("源路径", self._sources)
        form.addRow("", preset_row)
        form.addRow("目的路径", dest_row)
        form.addRow("保留份数", self._retention)
        form.addRow("", self._keep_monthly)
        form.addRow("", self._compress)
        form.addRow("压缩格式", self._format)
        form.addRow("压缩密码", self._password)
        form.addRow("排除规则", self._exclude)
        form.addRow("备份方式", self._backup_mode)
        form.addRow("恢复方式", self._restore_mode)
        form.addRow("链接类型", self._link_type)

        btns = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        btns.accepted.connect(self._accept)
        btns.rejected.connect(self.reject)
        lay = QVBoxLayout(self)
        lay.addLayout(form)
        lay.addWidget(btns)

    def _browse_dest(self):
        p = QFileDialog.getExistingDirectory(
            self, "选择目的目录", self._destination.text() or "")
        if p:
            self._destination.setText(p)

    def _accept(self):
        if not self._id.text().strip() or not self._name.text().strip():
            QMessageBox.warning(self, "输入不完整", "ID 和名称不能为空")
            return
        if not self._sources.paths():
            QMessageBox.warning(self, "输入不完整", "至少需要一个源路径")
            return
        self.accept()

    def plan(self) -> BackupPlan:
        if self._plan is None:
            self._plan = BackupPlan(id=self._id.text().strip(),
                                    name=self._name.text().strip())
        p = self._plan
        p.id = self._id.text().strip()
        p.name = self._name.text().strip()
        p.sources = self._sources.paths()
        dest = self._destination.text().strip()
        # 本地绝对路径统一分隔符并变量化（与源路径一致）；协议/相对路径原样保留
        if dest and os.path.isabs(os.path.expandvars(dest)):
            p.destination = compact(dest)
        else:
            p.destination = dest
        p.retention = self._retention.value()
        p.keep_monthly = self._keep_monthly.isChecked()
        p.compress = self._compress.isChecked()
        p.format = self._format.currentText()
        p.password = self._password.text()
        p.exclude = [l.strip() for l in self._exclude.toPlainText().splitlines() if l.strip()]
        p.backup_mode = self._backup_mode.currentData()
        p.restore_mode = self._restore_mode.currentData()
        p.link_type = self._link_type.currentData()
        if not p.created_at:
            p.created_at = now_iso()
        p.updated_at = now_iso()
        return p
