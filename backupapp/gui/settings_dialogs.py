"""自身备份设置对话框 + 全局计划任务控件。"""

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (QCheckBox, QComboBox, QDialog, QDialogButtonBox,
                               QFormLayout, QGroupBox, QHBoxLayout, QHeaderView,
                               QLabel, QLineEdit, QMessageBox, QProgressBar,
                               QPushButton, QSpinBox, QTableWidget,
                               QTableWidgetItem, QVBoxLayout)

from .. import scheduler as sched
from ..i18n import _
from ..storage import store
from ..util import format_size as _fmt_size

_PROTOCOLS = ["webdav", "s3", "ftp", "sftp"]
# i18n:data
_FREQ_LABEL = {"daily": "每天", "weekly": "每周", "days": "每N天",
               "hourly": "每N小时", "minutely": "每N分钟", "atLogon": "登录时"}
_FREQ_REV = {v: k for k, v in _FREQ_LABEL.items()}  # 中文 -> 英文（旧数据兼容）


class SelfBackupDialog(QDialog):
    """自身备份配置。每个协议独立保存（settings.json -> selfBackups[protocol]）。"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle(_("自身备份设置"))
        self.setMinimumWidth(460)
        cfg = store.load_settings()
        self._protocol = QComboBox()
        self._protocol.addItems(_PROTOCOLS)
        # 默认显示已启用的协议（没有则 webdav）
        enabled = [sb.protocol for sb in cfg.enabled_sbs()]
        default_proto = enabled[0] if enabled else "webdav"
        self._old_sb = cfg.sb(default_proto)
        self._current_proto = default_proto

        self._enabled = QCheckBox(_("启用自身备份"))
        self._host = QLineEdit()
        self._port = QLineEdit()
        self._remote_path = QLineEdit()
        self._username = QLineEdit()
        self._password = QLineEdit()
        self._password.setEchoMode(QLineEdit.Password)
        self._bucket = QLineEdit()
        self._region = QLineEdit()
        self._endpoint = QLineEdit()
        self._credential_store = QComboBox()
        self._credential_store.addItems(["plain", "dpapi", "keyring"])
        self._use_ssl = QCheckBox(_("使用 SSL/TLS"))
        self._timeout = QSpinBox()
        self._timeout.setRange(1, 600)
        self._timeout.setValue(10)
        self._timeout.setSuffix(_(" 秒"))
        self._retention = QSpinBox()
        self._retention.setRange(1, 9999)
        self._retention.setValue(30)
        self._compress = QCheckBox(_("压缩"))
        self._compress.setChecked(True)
        self._format = QComboBox()
        self._format.addItems(["zip", "7z", "tar.gz"])
        self._archive_password = QLineEdit()
        self._archive_password.setEchoMode(QLineEdit.Password)
        self._local_copy = QCheckBox(_("同时保留本地副本（data/backups）"))

        self._s3_box = QGroupBox(_("S3 专用"))
        s3f = QFormLayout(self._s3_box)
        s3f.addRow("Bucket", self._bucket)
        s3f.addRow("Region", self._region)
        s3f.addRow("Endpoint", self._endpoint)

        form = QFormLayout()
        form.addRow("", self._enabled)          # 0
        form.addRow(_("协议"), self._protocol)   # 1
        form.addRow(_("主机"), self._host)       # 2
        form.addRow(_("端口"), self._port)       # 3
        form.addRow(_("远程路径"), self._remote_path)  # 4
        form.addRow(_("用户名"), self._username)  # 5
        form.addRow(_("密码"), self._password)    # 6
        form.addRow(self._s3_box)               # 7
        form.addRow(_("凭据存储"), self._credential_store)  # 8
        form.addRow("", self._use_ssl)          # 9
        form.addRow(_("超时时间"), self._timeout)  # 10
        form.addRow(_("远程保留份数"), self._retention)  # 11
        form.addRow("", self._compress)         # 12
        form.addRow(_("压缩格式"), self._format)  # 13
        form.addRow(_("压缩包密码"), self._archive_password)  # 14
        form.addRow("", self._local_copy)       # 15
        self._form = form

        self._test_btn = QPushButton(_("测试连接"))
        self._test_btn.clicked.connect(self._test)
        form.addRow(self._test_btn)             # 16

        btns = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        btns.accepted.connect(self._save)
        btns.rejected.connect(self.reject)
        lay = QVBoxLayout(self)
        lay.addLayout(form)
        lay.addWidget(btns)
        self._protocol.currentTextChanged.connect(self._on_protocol_changed)
        # 初始化各协议字段（切协议时把当前表单值先写回原协议，再载入新协议）
        self._field_state: dict[str, dict] = {}
        self._protocol.setCurrentText(self._old_sb.protocol)
        self._load_sb(self._old_sb)

    def _snapshot_fields(self) -> dict:
        """当前表单值 -> dict（按协议暂存）。"""
        sb = self._collect()
        return {k: v for k, v in sb.__dict__.items() if k != "protocol"}

    def _on_protocol_changed(self, proto: str):
        if self._current_proto == proto:
            return
        # 先把当前协议的表单值快照暂存，再载入新协议
        self._field_state[self._current_proto] = self._snapshot_fields()
        self._current_proto = proto
        st = self._field_state.get(proto)
        if st:
            from ..model import SelfBackup
            self._load_sb(SelfBackup(protocol=proto, **st))
        else:
            self._load_sb(store.load_settings().sb(proto))
        self._old_sb = store.load_settings().sb(proto)

    def _load_sb(self, sb):
        self._enabled.setChecked(sb.enabled)
        self._host.setText(sb.host)
        self._port.setText(str(sb.port) if sb.port else "")
        self._remote_path.setText(sb.remote_path)
        self._username.setText(sb.username)
        self._password.setText(sb.password if sb.credential_store == "plain" else "")
        self._password.setPlaceholderText(
            "" if sb.credential_store == "plain" else _("已加密存储，留空保持原值"))
        self._bucket.setText(sb.bucket)
        self._region.setText(sb.region)
        self._endpoint.setText(sb.endpoint)
        self._credential_store.setCurrentText(sb.credential_store or "plain")
        self._use_ssl.setChecked(sb.use_ssl)
        self._timeout.setValue(sb.timeout or 10)
        self._retention.setValue(sb.retention or 30)
        self._compress.setChecked(sb.compress)
        self._format.setCurrentText(sb.format or "zip")
        self._archive_password.setText(
            sb.archive_password if sb.credential_store == "plain" else "")
        self._archive_password.setPlaceholderText(
            "" if sb.credential_store == "plain" else _("已加密存储，留空保持原值"))
        self._local_copy.setChecked(sb.local_copy)
        self._sync_s3(sb.protocol)

    def _sync_s3(self, proto: str):
        """S3 用 endpoint/bucket 寻址，隐藏 主机/端口 行；字段标签按协议改名。"""
        is_s3 = proto == "s3"
        self._s3_box.setVisible(is_s3)
        # 行索引见 __init__ 注释
        self._form.setRowVisible(2, not is_s3)  # 主机
        self._form.setRowVisible(3, not is_s3)  # 端口
        # S3: 用户名=Access Key、密码=Secret Key、远程路径=Prefix
        lbl = self._form.labelForField
        lbl(self._username).setText(_("Access Key") if is_s3 else _("用户名"))
        lbl(self._password).setText(_("Secret Key") if is_s3 else _("密码"))
        lbl(self._remote_path).setText(_("Prefix") if is_s3 else _("远程路径"))
        # 行显隐后窗口高度不自动收缩，adjustSize 让按钮回到可视区
        self.adjustSize()

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
            timeout=self._timeout.value(),
            retention=self._retention.value(),
            compress=self._compress.isChecked(),
            format=self._format.currentText(),
            archive_password=self._archive_password.text(),
            local_copy=self._local_copy.isChecked(),
        )

    def _test(self):
        from .workers import TestWorker
        sb = self._collect()
        if sb.protocol == "s3":
            missing = [f for f, v in (("Endpoint", sb.endpoint),
                                      ("Bucket", sb.bucket),
                                      ("Access Key", sb.username),
                                      ("Secret Key", sb.password)) if not v]
            if missing:
                QMessageBox.warning(self, _("测试连接"),
                                    _("请先填写: {missing}").format(
                                        missing=", ".join(missing)))
                return
        elif not sb.host:
            QMessageBox.warning(self, _("测试连接"), _("请先填写主机地址"))
            return
        self._test_btn.setEnabled(False)
        self._test_btn.setText(_("测试中..."))
        w = TestWorker(sb, self)
        self._test_worker = w

        def _done(ok: bool, msg: str):
            self._test_btn.setEnabled(True)
            self._test_btn.setText(_("测试连接"))
            if ok:
                QMessageBox.information(self, _("测试连接"),
                                        _("连接成功：{msg}").format(msg=msg))
            else:
                QMessageBox.critical(self, _("测试连接"),
                                     _("连接失败：{msg}").format(msg=msg))

        w.done.connect(_done)
        w.finished.connect(w.deleteLater)
        w.start()

    def _save(self):
        from .. import security
        cfg = store.load_settings()
        # 各协议独立保存：写回当前协议配置，不影响其他协议
        sb = self._collect()
        # 未勾选启用时询问：避免保存了配置却忘了启用导致备份不执行
        if not sb.enabled:
            ret = QMessageBox.question(
                self, _("自身备份"),
                _("当前未勾选“启用自身备份”，保存后备份不会执行。\n"
                  "是否现在启用？"))
            if ret == QMessageBox.Yes:
                sb.enabled = True
        old = store.load_settings().sb(sb.protocol)
        kind = sb.credential_store
        if kind == "plain":
            if old.credential_store != "plain" and not sb.password:
                QMessageBox.warning(
                    self, _("凭据"),
                    _("密码字段为空，将保留原加密值；如需以明文保存请重新输入密码。"))
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
                security.keyring_set(security._KEY_REMOTE + f"_{sb.protocol}",
                                     sb.password or "")
                security.keyring_set(security._KEY_ARCHIVE + f"_{sb.protocol}",
                                     sb.archive_password or "")
                sb.password = ""
                sb.archive_password = ""
        # 单协议启用：保存当前协议时，其他协议一律停用，
        # 避免"启用 s3 时 webdav 也跟着启用"（enabled_sbs 会同时返回两者）
        if sb.enabled:
            for proto, other in cfg.self_backups.items():
                if proto != sb.protocol:
                    other.enabled = False
        cfg.self_backups[sb.protocol] = sb
        store.save_settings(cfg)
        self.accept()


class SchedulerGroup(QGroupBox):
    """全局计划任务：点击"注册"创建系统任务，"取消注册"删除。"""

    def __init__(self, parent=None):
        super().__init__(_("全局计划任务"), parent)
        s = store.load_settings().scheduler

        self._freq = QComboBox()
        for val, label in _FREQ_LABEL.items():  # 中文显示，英文存储
            self._freq.addItem(_(label), val)
        self._freq.setCurrentIndex(max(0, self._freq.findData(
            _FREQ_REV.get(s.frequency, s.frequency))))
        self._freq.currentIndexChanged.connect(self._sync)
        self._freq.setMaxVisibleItems(12)
        self._interval = QSpinBox()
        self._interval.setRange(1, 999)
        self._interval.setValue(s.interval if s.interval >= 1 else 1)
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
        # 周几：下拉选择（与计划对话框一致，走翻译）
        self._day = QComboBox()
        for d in range(1, 8):
            self._day.addItem(_("周{day}").format(day="一二三四五六日"[d - 1]), d)
        self._day.setCurrentIndex(s.day_of_week - 1 if 1 <= s.day_of_week <= 7 else 0)
        self._apply = QPushButton(_("注册"))
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
        g1 = group(); g1.addWidget(QLabel(_("频率"))); g1.addWidget(self._freq); g1.addWidget(self._interval)
        main.addLayout(g1)
        g2 = group(); g2.addWidget(QLabel(_("时间"))); g2.addWidget(self._time)
        main.addLayout(g2)
        g3 = group(); g3.addWidget(QLabel(_("星期"))); g3.addWidget(self._day)
        main.addLayout(g3)
        main.addStretch(1)
        main.addWidget(self._apply)
        main.addWidget(self._status)
        self._sync()  # 按频率联动：间隔/时间/星期
        self.set_state(None)
        # 注册/取消注册后的状态由主窗口后台刷新（回调），避免界面内再起子进程
        self.after_change = None
        # 注册/取消注册的执行入口，由主窗口注入（后台 worker）；None 时同步兜底
        self.apply_task = None

    def _sync(self):
        f = self._freq.currentData()
        interval_mode = f in ("days", "hourly", "minutely")
        self._interval.setVisible(interval_mode)
        self._time.setEnabled(f in ("daily", "weekly"))
        self._day.setEnabled(f == "weekly")

    def set_state(self, st: str | None):
        """按后台查询结果更新状态文案与按钮（None = 查询中）。"""
        self._st = st
        if st is None:
            self._status.setText(_("状态: {text}").format(text=_("查询中...")))
            self._status.setStyleSheet("color: gray;")
            return
        text = {"registered": _("已注册"), "missing": _("未注册"),
                "pathMismatch": _("路径变更，需重新应用")}.get(st, st)
        color = "green" if st == "registered" else "gray"
        self._status.setText(_("状态: {text}").format(text=text))
        self._status.setStyleSheet(f"color: {color};")
        self._apply.setText(_("取消注册") if st == "registered" else _("注册"))

    def _read_form(self, cfg) -> None:
        freq = self._freq.currentData()
        cfg.scheduler.frequency = _FREQ_REV.get(freq, freq)  # 兼容旧版存的中文
        cfg.scheduler.time = self._time.currentData()
        cfg.scheduler.day_of_week = self._day.currentData()
        cfg.scheduler.interval = self._interval.value()
        store.save_settings(cfg)

    def _apply_clicked(self):
        """点击注册/取消注册操作系统任务（按当前显示的注册状态切换）。

        schtasks 子进程冷缓存可达数秒，不能在 UI 线程同步执行：委托主窗口的
        worker 管理器后台执行（apply_task 回调），结果回来后由主窗口统一刷新。
        """
        cfg = store.load_settings()
        self._read_form(cfg)
        op = "global_uninstall" if self._st == "registered" else "global_install"
        self._st = None
        self.set_state(None)  # 状态未知，等后台刷新
        if self.apply_task:
            self.apply_task([(op, "", "")])
        else:  # 独立使用时无主窗口可委托：同步执行（仅测试/兜底）
            err = sched.uninstall(cfg) if op == "global_uninstall" else sched.install(cfg)
            if err:
                QMessageBox.warning(self, _("计划任务"),
                                    _("操作失败：{err}").format(err=err))
            if self.after_change:
                self.after_change()


class SelfBackupFilesDialog(QDialog):
    """远程自身备份文件管理：列出（文件名/大小/备份时间），可恢复或删除。"""

    restored = Signal()  # 数据被恢复/删除后发出，主窗口据此刷新应用列表

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle(_("自身备份文件"))
        self.resize(720, 420)
        cfg = store.load_settings()
        self._protocol = QComboBox()
        self._protocol.addItems(_PROTOCOLS)
        # 默认选中第一个已启用的协议（没有则 webdav）
        enabled = [sb.protocol for sb in cfg.enabled_sbs()]
        default = enabled[0] if enabled else "webdav"
        self._protocol.setCurrentText(default)
        self._protocol.currentIndexChanged.connect(self._refresh)

        lay = QVBoxLayout(self)
        top = QHBoxLayout()
        top.addWidget(QLabel(_("协议:")))
        top.addWidget(self._protocol)
        self._status = QLabel("")
        top.addWidget(self._status, 1)
        lay.addLayout(top)

        self._table = QTableWidget(0, 3)
        self._table.setHorizontalHeaderLabels(
            [_("文件名"), _("大小"), _("备份时间")])
        header = self._table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.Stretch)
        header.setSectionResizeMode(1, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(2, QHeaderView.ResizeToContents)
        self._table.setSelectionBehavior(QTableWidget.SelectRows)
        self._table.setSelectionMode(QTableWidget.SingleSelection)
        self._table.setEditTriggers(QTableWidget.NoEditTriggers)
        self._table.doubleClicked.connect(self._restore_selected)
        lay.addWidget(self._table, 1)

        btns = QHBoxLayout()
        self._btn_refresh = QPushButton(_("刷新"))
        self._btn_restore = QPushButton(_("恢复选中"))
        self._btn_delete = QPushButton(_("删除选中"))
        self._btn_close = QPushButton(_("关闭"))
        self._btn_refresh.clicked.connect(self._refresh)
        self._btn_restore.clicked.connect(self._restore_selected)
        self._btn_delete.clicked.connect(self._delete_selected)
        self._btn_close.clicked.connect(self.accept)
        btns.addWidget(self._btn_refresh)
        btns.addWidget(self._btn_restore)
        btns.addWidget(self._btn_delete)
        btns.addStretch(1)
        btns.addWidget(self._btn_close)
        lay.addLayout(btns)

        # 操作进行中的不定进度动画（恢复/删除时显示）
        self._busy_bar = QProgressBar()
        self._busy_bar.setRange(0, 0)
        self._busy_bar.setFixedHeight(8)
        self._busy_bar.setTextVisible(False)
        self._busy_bar.hide()
        lay.addWidget(self._busy_bar)

        self._workers: list = []
        self._busy = False  # 增删改查进行中：避免重复起 worker
        self._refresh()

    # ---- 列表 ----

    def _refresh(self):
        from .workers import SelfListWorker
        # 单飞：切换协议或连点刷新时旧请求可能仍在途，并发会让后到的结果覆盖
        # 新协议的数据。注意不能用 isRunning() 判断——本方法也会从恢复/删除的
        # 完成回调里调用，那时对应 worker 的 run() 可能尚未返回。
        if self._busy:
            return
        self._busy = True
        self._table.setRowCount(0)
        self._status.setText(_("加载中..."))
        self._set_busy(True)
        protocol = self._protocol.currentText()
        w = SelfListWorker(protocol, self)
        self._workers.append(w)

        def _done(files, err: str):
            if w in self._workers:
                self._workers.remove(w)
            self._busy = False
            self._set_busy(False)
            # 结果回来时协议可能已经切走：丢弃过期响应
            if self._protocol.currentText() != protocol:
                return
            if err:
                self._status.setText(_("加载失败: {err}").format(err=err))
                return
            self._populate(files or [])
            self._status.setText(_("共 {n} 个备份").format(n=len(files or [])))

        w.done.connect(_done)
        w.finished.connect(w.deleteLater)
        w.start()

    def closeEvent(self, event):
        """关闭时等待在途的列表/恢复/删除 worker，避免 QThread 运行中被销毁。"""
        for w in list(self._workers):
            if w.isRunning():
                w.requestInterruption()
                if not w.wait(10000):
                    w.terminate()
                    w.wait(1000)
        super().closeEvent(event)

    def _populate(self, files):
        from ..protocols.base import RemoteFile  # noqa: F401 (类型提示)
        self._table.setRowCount(len(files))
        for row, f in enumerate(files):
            name_item = QTableWidgetItem(f.name)
            name_item.setToolTip(f.name)
            size_item = QTableWidgetItem(_fmt_size(f.size))
            size_item.setToolTip(_("{size} 字节").format(size=f.size) if f.size else "-")
            ts = f.mtime.replace("T", " ")[:19] if f.mtime else "-"
            time_item = QTableWidgetItem(ts)
            time_item.setToolTip(f.mtime if f.mtime else "-")
            self._table.setItem(row, 0, name_item)
            self._table.setItem(row, 1, size_item)
            self._table.setItem(row, 2, time_item)

    def _selected_name(self) -> str | None:
        row = self._table.currentRow()
        if row < 0:
            return None
        return self._table.item(row, 0).text()

    # ---- 操作 ----

    def _restore_selected(self, *_args):
        if self._busy:
            return  # 已有请求在途，忽略重复触发
        name = self._selected_name()
        if not name:
            QMessageBox.information(self, _("恢复"), _("请先选择一个备份文件"))
            return
        box = QMessageBox(self)
        box.setWindowTitle(_("恢复自身备份"))
        box.setIcon(QMessageBox.Question)
        box.setText(_("将从远程恢复 {name}，覆盖当前 apps/ 与 settings.json？\n"
                      "（恢复前会把当前数据移到 data/self_restore_old_* 备份）"
                      ).format(name=name))
        overwrite_btn = box.addButton(_("覆盖（推荐）"), QMessageBox.YesRole)
        merge_btn = box.addButton(_("仅新增（保留现有同 ID 应用）"),
                                  QMessageBox.NoRole)
        cancel_btn = box.addButton(_("取消"), QMessageBox.RejectRole)
        box.exec()
        if box.clickedButton() is cancel_btn:
            return
        overwrite = box.clickedButton() is overwrite_btn
        from .workers import SelfRestoreWorker
        proto = self._protocol.currentText()
        self._busy = True
        self._set_busy(True)
        w = SelfRestoreWorker(proto, name, overwrite, self)
        self._workers.append(w)

        def _done(ok: bool, msg: str):
            self._busy = False
            self._set_busy(False)
            if w in self._workers:
                self._workers.remove(w)
            if ok:
                QMessageBox.information(self, _("恢复"),
                                        _("恢复成功：{msg}").format(msg=msg))
                self._refresh()
                self.restored.emit()
            else:
                QMessageBox.critical(self, _("恢复失败"), msg)

        w.done.connect(_done)
        w.finished.connect(w.deleteLater)
        w.start()

    def _delete_selected(self):
        if self._busy:
            return  # 已有请求在途，忽略重复触发
        name = self._selected_name()
        if not name:
            QMessageBox.information(self, _("删除"), _("请先选择一个备份文件"))
            return
        ret = QMessageBox.question(self, _("删除备份"),
                                   _("确定删除远程备份 {name}？").format(name=name))
        if ret != QMessageBox.Yes:
            return
        from .workers import SelfDeleteWorker
        proto = self._protocol.currentText()
        self._busy = True
        self._set_busy(True)
        w = SelfDeleteWorker(proto, name, self)
        self._workers.append(w)

        def _done(ok: bool, msg: str):
            self._busy = False
            self._set_busy(False)
            if w in self._workers:
                self._workers.remove(w)
            if ok:
                self._status.setText(msg)
                self._refresh()
                self.restored.emit()
            else:
                QMessageBox.critical(self, _("删除失败"), msg)

        w.done.connect(_done)
        w.finished.connect(w.deleteLater)
        w.start()

    def _set_busy(self, busy: bool):
        for b in (self._btn_refresh, self._btn_restore, self._btn_delete,
                  self._protocol):
            b.setEnabled(not busy)
        # 表格也要禁用：它的 doubleClicked 仍连着 _restore_selected，
        # 恢复/删除进行中再双击会起第二个 worker（并发覆盖同一份数据）。
        self._table.setEnabled(not busy)
        # 进行中显示不定进度动画（右下角状态栏同样由主窗口 busy_bar 呈现）
        self._busy_bar.setVisible(busy)
        if busy:
            self._status.setText(_("处理中..."))
