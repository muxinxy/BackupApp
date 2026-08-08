"""自身备份设置对话框 + 全局计划任务控件。"""

from PySide6.QtWidgets import (QCheckBox, QComboBox, QDialog, QDialogButtonBox,
                               QFormLayout, QGroupBox, QHBoxLayout, QLabel,
                               QLineEdit, QMessageBox, QPushButton, QSpinBox,
                               QVBoxLayout)

from .. import scheduler as sched
from ..storage import store

_PROTOCOLS = ["webdav", "s3", "ftp", "sftp"]
_FREQ_LABEL = {"daily": "每天", "weekly": "每周", "atLogon": "登录时"}
_FREQ_REV = {v: k for k, v in _FREQ_LABEL.items()}  # 中文 -> 英文（旧数据兼容）


class SelfBackupDialog(QDialog):
    """自身备份配置。协议模块（webdav/s3/ftp/sftp）下一阶段实现。"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("自身备份设置")
        self.setMinimumWidth(460)
        sb = store.load_settings().self_backup
        self._old_sb = sb

        self._enabled = QCheckBox("启用自身备份")
        self._enabled.setChecked(sb.enabled)
        self._protocol = QComboBox()
        self._protocol.addItems(_PROTOCOLS)
        self._protocol.setCurrentText(sb.protocol or "webdav")
        self._host = QLineEdit(sb.host)
        self._port = QLineEdit(str(sb.port) if sb.port else "")
        self._remote_path = QLineEdit(sb.remote_path)
        self._username = QLineEdit(sb.username)
        self._password = QLineEdit(sb.password if sb.credential_store == "plain" else "")
        self._password.setEchoMode(QLineEdit.Password)
        if sb.credential_store != "plain":
            self._password.setPlaceholderText("已加密存储，留空保持原值")
        self._bucket = QLineEdit(sb.bucket)
        self._region = QLineEdit(sb.region)
        self._endpoint = QLineEdit(sb.endpoint)
        self._credential_store = QComboBox()
        self._credential_store.addItems(["plain", "dpapi", "keyring"])
        self._credential_store.setCurrentText(sb.credential_store or "plain")
        self._use_ssl = QCheckBox("使用 SSL/TLS")
        self._use_ssl.setChecked(sb.use_ssl)
        self._retention = QSpinBox()
        self._retention.setRange(1, 9999)
        self._retention.setValue(sb.retention or 30)
        self._compress = QCheckBox("压缩")
        self._compress.setChecked(sb.compress)
        self._format = QComboBox()
        self._format.addItems(["zip", "7z", "tar.gz"])
        self._format.setCurrentText(sb.format or "zip")
        self._archive_password = QLineEdit(
            sb.archive_password if sb.credential_store == "plain" else "")
        self._archive_password.setEchoMode(QLineEdit.Password)
        if sb.credential_store != "plain":
            self._archive_password.setPlaceholderText("已加密存储，留空保持原值")
        self._local_copy = QCheckBox("同时保留本地副本（data/backups）")
        self._local_copy.setChecked(sb.local_copy)

        self._s3_box = QGroupBox("S3 专用")
        s3f = QFormLayout(self._s3_box)
        s3f.addRow("Bucket", self._bucket)
        s3f.addRow("Region", self._region)
        s3f.addRow("Endpoint", self._endpoint)

        form = QFormLayout()
        form.addRow("", self._enabled)
        form.addRow("协议", self._protocol)
        form.addRow("主机", self._host)
        form.addRow("端口", self._port)
        form.addRow("远程路径", self._remote_path)
        form.addRow("用户名", self._username)
        form.addRow("密码", self._password)
        form.addRow(self._s3_box)
        form.addRow("凭据存储", self._credential_store)
        form.addRow("", self._use_ssl)
        form.addRow("远程保留份数", self._retention)
        form.addRow("", self._compress)
        form.addRow("压缩格式", self._format)
        form.addRow("压缩包密码", self._archive_password)
        form.addRow("", self._local_copy)

        self._test_btn = QPushButton("测试连接")
        self._test_btn.clicked.connect(self._test)
        form.addRow(self._test_btn)

        btns = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        btns.accepted.connect(self._save)
        btns.rejected.connect(self.reject)
        lay = QVBoxLayout(self)
        lay.addLayout(form)
        lay.addWidget(btns)
        self._protocol.currentTextChanged.connect(self._sync_s3)
        self._sync_s3(self._protocol.currentText())

    def _sync_s3(self, proto: str):
        self._s3_box.setVisible(proto == "s3")

    def _collect(self):
        """从表单构造 SelfBackup（不写盘）。"""
        from ..model import SelfBackup
        port = self._port.text().strip()
        return SelfBackup(
            enabled=self._enabled.isChecked(),
            protocol=self._protocol.currentText(),
            host=self._host.text().strip(),
            port=int(port) if port else None,
            remote_path=self._remote_path.text().strip(),
            username=self._username.text().strip(),
            password=self._password.text(),
            bucket=self._bucket.text().strip(),
            region=self._region.text().strip(),
            endpoint=self._endpoint.text().strip(),
            credential_store=self._credential_store.currentText(),
            use_ssl=self._use_ssl.isChecked(),
            retention=self._retention.value(),
            compress=self._compress.isChecked(),
            format=self._format.currentText(),
            archive_password=self._archive_password.text(),
            local_copy=self._local_copy.isChecked(),
        )

    def _test(self):
        from .workers import TestWorker
        sb = self._collect()
        if not sb.host:
            QMessageBox.warning(self, "测试连接", "请先填写主机地址")
            return
        self._test_btn.setEnabled(False)
        self._test_btn.setText("测试中...")
        w = TestWorker(sb, self)
        self._test_worker = w

        def _done(ok: bool, msg: str):
            self._test_btn.setEnabled(True)
            self._test_btn.setText("测试连接")
            if ok:
                QMessageBox.information(self, "测试连接", f"连接成功：{msg}")
            else:
                QMessageBox.critical(self, "测试连接", f"连接失败：{msg}")

        w.done.connect(_done)
        w.finished.connect(w.deleteLater)
        w.start()

    def _save(self):
        from .. import security
        cfg = store.load_settings()
        sb = self._collect()
        old = self._old_sb
        kind = sb.credential_store
        if kind == "plain":
            if old.credential_store != "plain" and not sb.password:
                QMessageBox.warning(
                    self, "凭据",
                    "密码字段为空，将保留原加密值；如需以明文保存请重新输入密码。")
                sb.password = old.password
                sb.archive_password = old.archive_password
        else:
            if sb.password:
                sb.password = security.encrypt_secret(sb.password, kind)
            else:
                sb.password = old.password  # 保留已存值（密文/明文原样）
            if sb.archive_password:
                sb.archive_password = security.encrypt_secret(sb.archive_password, kind)
            else:
                sb.archive_password = old.archive_password
            if kind == "keyring":
                security.keyring_set(security._KEY_REMOTE, sb.password or "")
                security.keyring_set(security._KEY_ARCHIVE, sb.archive_password or "")
                sb.password = ""
                sb.archive_password = ""
        cfg.self_backup = sb
        store.save_settings(cfg)
        self.accept()


class SchedulerGroup(QGroupBox):
    """全局计划任务：勾选启用仅改设置，点击"注册"才创建/删除系统任务。"""

    def __init__(self, parent=None):
        super().__init__("全局计划任务", parent)
        s = store.load_settings().scheduler

        self._enabled = QCheckBox("启用")
        self._enabled.setChecked(s.enabled)
        self._freq = QComboBox()
        for val, label in _FREQ_LABEL.items():  # 中文显示，英文存储
            self._freq.addItem(label, val)
        self._freq.setCurrentIndex(max(0, self._freq.findData(
            _FREQ_REV.get(s.frequency, s.frequency))))
        self._freq.currentIndexChanged.connect(self._sync_day)
        # 时间：下拉选择（每 30 分钟；保存过自定义时间则保留）
        self._time = QComboBox()
        cur = s.time or "02:30"
        if cur not in {f"{h:02d}:{m:02d}" for h in range(24) for m in (0, 30)}:
            self._time.addItem(cur, cur)
        for h in range(24):
            for m in (0, 30):
                t = f"{h:02d}:{m:02d}"
                self._time.addItem(t, t)
        self._time.setCurrentIndex(self._time.findData(cur))
        # 周几：下拉选择
        self._day = QComboBox()
        for d in range(1, 8):
            self._day.addItem(f"周{'一二三四五六日'[d - 1]}", d)
        self._day.setCurrentIndex(s.day_of_week - 1 if 1 <= s.day_of_week <= 7 else 0)
        self._apply = QPushButton("注册")
        self._apply.clicked.connect(self._apply_clicked)
        self._status = QLabel()

        def group():
            g = QHBoxLayout()
            g.setSpacing(2)  # 组内紧凑
            return g

        self._freq.setMinimumWidth(110)
        self._time.setMinimumWidth(100)
        self._day.setMinimumWidth(76)

        main = QHBoxLayout(self)
        main.setSpacing(16)  # 组间疏
        g0 = group(); g0.addWidget(self._enabled)
        main.addLayout(g0)
        g1 = group(); g1.addWidget(QLabel("频率")); g1.addWidget(self._freq)
        main.addLayout(g1)
        g2 = group(); g2.addWidget(QLabel("时间")); g2.addWidget(self._time)
        main.addLayout(g2)
        g3 = group(); g3.addWidget(QLabel("周几")); g3.addWidget(self._day)
        main.addLayout(g3)
        main.addStretch(1)
        main.addWidget(self._apply)
        main.addWidget(self._status)
        self._sync_day()  # 非每周时周几置灰
        self.refresh_status()

    def _sync_day(self):
        self._day.setEnabled(self._freq.currentData() == "weekly")

    def refresh_status(self):
        st = sched.status(store.load_settings())
        text = {"registered": "已注册", "missing": "未注册",
                "pathMismatch": "路径变更，需重新应用"}.get(st, st)
        color = "green" if st == "registered" else "gray"
        self._status.setText(f"状态: {text}")
        self._status.setStyleSheet(f"color: {color};")

    def _read_form(self, cfg) -> None:
        cfg.scheduler.enabled = self._enabled.isChecked()
        freq = self._freq.currentData()
        cfg.scheduler.frequency = _FREQ_REV.get(freq, freq)  # 兼容旧版存的中文
        cfg.scheduler.time = self._time.currentData()
        cfg.scheduler.day_of_week = self._day.currentData()
        store.save_settings(cfg)

    def _apply_clicked(self):
        """点击注册才创建/删除系统任务；仅勾选启用不注册。"""
        cfg = store.load_settings()
        self._read_form(cfg)
        if cfg.scheduler.enabled:
            if not sched.install(cfg):
                QMessageBox.warning(self, "计划任务", "注册失败")
        else:
            sched.uninstall(cfg)
        self.refresh_status()
