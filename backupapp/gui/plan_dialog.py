"""备份计划新增/编辑对话框。"""

import os
from datetime import datetime

from PySide6.QtWidgets import (QCheckBox, QComboBox, QDialog, QDialogButtonBox,
                               QFileDialog, QFormLayout, QHBoxLayout, QLabel,
                               QLineEdit, QMessageBox, QPlainTextEdit, QPushButton,
                               QSpinBox, QVBoxLayout)

from ..engine.paths import compact
from ..model import AppConfig, BackupPlan, now_iso
from .widgets import PathListEditor, WheelLock


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
        self._wheel_locks = [WheelLock(self._retention)]  # 持引用防 GC，禁滚轮保留输入
        self._retention.setRange(1, 9999)
        self._retention.setValue(plan.retention if plan else 14)
        self._retention_unit = QComboBox()
        self._retention_unit.addItem("份", "count")
        self._retention_unit.addItem("天", "days")
        self._retention_unit.setCurrentIndex(
            0 if (plan is None or plan.retention_unit == "count") else 1)
        retention_row = QHBoxLayout()
        retention_row.addWidget(self._retention)
        retention_row.addWidget(self._retention_unit)
        self._keep_monthly = QCheckBox("额外保留每月第一份")
        self._keep_monthly.setChecked(plan.keep_monthly if plan else True)
        self._keep_yearly = QCheckBox("额外保留每年第一份")
        self._keep_yearly.setChecked(plan.keep_yearly if plan else False)
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

        # 命令/脚本钩子：备份前/后执行，可设超时
        self._pre_cmd = QLineEdit(plan.pre_cmd if plan else "")
        self._pre_cmd.setPlaceholderText(
            "备份开始前执行（非零退出或超时则中止本次备份），如 net stop MyService")
        self._post_cmd = QLineEdit(plan.post_cmd if plan else "")
        self._post_cmd.setPlaceholderText(
            "备份完成后执行（失败仅记日志），如 net start MyService")
        self._cmd_timeout = QSpinBox()
        self._wheel_locks.append(WheelLock(self._cmd_timeout))
        self._cmd_timeout.setRange(1, 3600)
        self._cmd_timeout.setValue(plan.cmd_timeout if plan else 60)
        self._cmd_timeout.setSuffix(" 秒")
        timeout_row = QHBoxLayout()
        timeout_row.addWidget(self._cmd_timeout)

        # 计划任务排期：与全局一致，或自定义
        self._schedule_mode = QComboBox()
        self._schedule_mode.addItem("与全局一致", "global")
        self._schedule_mode.addItem("自定义", "custom")
        self._schedule_mode.setCurrentIndex(
            0 if (plan is None or plan.schedule_mode == "global") else 1)
        self._schedule_freq = QComboBox()
        for val, label in (("daily", "每天"), ("weekly", "每周"), ("days", "每N天"),
                           ("hourly", "每N小时"), ("minutely", "每N分钟"),
                           ("atLogon", "登录时")):
            self._schedule_freq.addItem(label, val)
        self._schedule_freq.setCurrentIndex(max(0, self._schedule_freq.findData(
            plan.schedule_frequency if plan else "daily")))
        self._schedule_interval = QSpinBox()
        self._schedule_interval.setRange(1, 999)
        self._schedule_interval.setValue(plan.schedule_interval if plan else 1)
        freq_row = QHBoxLayout()
        freq_row.addWidget(self._schedule_freq)
        freq_row.addWidget(self._schedule_interval)
        self._schedule_time = QComboBox()
        cur = plan.schedule_time if plan else "02:30"
        if cur not in {f"{h:02d}:{m:02d}" for h in range(24) for m in (0, 30)}:
            self._schedule_time.addItem(cur, cur)
        for h in range(24):
            for m in (0, 30):
                t = f"{h:02d}:{m:02d}"
                self._schedule_time.addItem(t, t)
        self._schedule_time.setCurrentIndex(self._schedule_time.findData(cur))
        self._schedule_day = QComboBox()
        for d in range(1, 8):
            self._schedule_day.addItem(f"周{'一二三四五六日'[d - 1]}", d)
        self._schedule_day.setCurrentIndex(
            plan.schedule_day_of_week - 1 if plan and 1 <= plan.schedule_day_of_week <= 7 else 0)
        self._schedule_mode.currentIndexChanged.connect(self._sync_schedule)
        self._schedule_freq.currentIndexChanged.connect(self._sync_schedule)
        self._sync_schedule()

        form = QFormLayout()
        form.addRow("ID", self._id)
        form.addRow("名称", self._name)
        form.addRow("源路径", self._sources)
        form.addRow("", preset_row)
        form.addRow("目的路径", dest_row)
        form.addRow("保留", retention_row)
        form.addRow("", self._keep_monthly)
        form.addRow("", self._keep_yearly)
        form.addRow("", self._compress)
        form.addRow("压缩格式", self._format)
        form.addRow("压缩密码", self._password)
        form.addRow("排除规则", self._exclude)
        form.addRow("备份方式", self._backup_mode)
        form.addRow("恢复方式", self._restore_mode)
        form.addRow("链接类型", self._link_type)
        form.addRow("备份前命令", self._pre_cmd)
        form.addRow("备份后命令", self._post_cmd)
        form.addRow("命令超时", timeout_row)
        form.addRow("计划任务", self._schedule_mode)
        form.addRow("频率", freq_row)
        form.addRow("时间", self._schedule_time)
        form.addRow("星期", self._schedule_day)

        # 内容较多：表单放入滚动区并限制高度，保证底部按钮始终可见
        from PySide6.QtWidgets import QApplication, QScrollArea, QWidget
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        form_host = QWidget()
        form_host.setLayout(form)
        scroll.setWidget(form_host)
        scr = QApplication.primaryScreen()
        if scr:
            self.setMaximumHeight(int(scr.availableGeometry().height() * 0.85))

        btns = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        btns.accepted.connect(self._accept)
        btns.rejected.connect(self.reject)
        lay = QVBoxLayout(self)
        lay.addWidget(scroll)
        lay.addWidget(btns)

    def _sync_schedule(self):
        """与全局一致时置灰自定义排期；间隔/时间/星期按频率联动。"""
        custom = self._schedule_mode.currentData() == "custom"
        f = self._schedule_freq.currentData()
        interval_mode = f in ("days", "hourly", "minutely")
        self._schedule_freq.setEnabled(custom)
        self._schedule_interval.setVisible(custom and interval_mode)
        self._schedule_time.setEnabled(custom and f in ("daily", "weekly"))
        self._schedule_day.setEnabled(custom and f == "weekly")

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
        p.retention_unit = self._retention_unit.currentData()
        p.keep_monthly = self._keep_monthly.isChecked()
        p.keep_yearly = self._keep_yearly.isChecked()
        p.compress = self._compress.isChecked()
        p.format = self._format.currentText()
        p.password = self._password.text()
        p.exclude = [l.strip() for l in self._exclude.toPlainText().splitlines() if l.strip()]
        p.backup_mode = self._backup_mode.currentData()
        p.restore_mode = self._restore_mode.currentData()
        p.link_type = self._link_type.currentData()
        p.pre_cmd = self._pre_cmd.text().strip()
        p.post_cmd = self._post_cmd.text().strip()
        p.cmd_timeout = self._cmd_timeout.value()
        p.schedule_mode = self._schedule_mode.currentData()
        p.schedule_frequency = self._schedule_freq.currentData()
        p.schedule_time = self._schedule_time.currentData()
        p.schedule_day_of_week = self._schedule_day.currentData()
        p.schedule_interval = self._schedule_interval.value()
        if not p.created_at:
            p.created_at = now_iso()
        p.updated_at = now_iso()
        return p
