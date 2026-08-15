"""主窗口：应用列表 + 计划表格 + 日志面板 + 工具栏（调度/自身备份/脚本）。"""

import os
from datetime import datetime

from PySide6.QtCore import Qt
from PySide6.QtGui import QAction, QBrush, QColor
from PySide6.QtWidgets import (QCheckBox, QComboBox, QDialog, QDialogButtonBox,
                               QFileDialog, QFormLayout, QHBoxLayout, QHeaderView,
                               QLabel, QListWidget, QListWidgetItem,
                               QMainWindow, QMessageBox, QPlainTextEdit, QProgressBar,
                               QPushButton, QSplitter, QTableWidget, QTableWidgetItem,
                               QToolBar, QVBoxLayout, QWidget)

from ..model import BackupPlan
from .. import __version__
from ..storage import importexport, store
from .app_dialog import AppDialog
from .plan_dialog import PlanDialog
from .settings_dialogs import SchedulerGroup, SelfBackupDialog, SelfBackupFilesDialog
from .workers import BackupWorker, RestoreWorker

_PLAN_COLS = ["启用", "名称", "源", "目的", "保留", "格式", "创建时间", "修改时间", "状态", "任务"]


def _fmt_ts(iso: str | None) -> str:
    """ISO 时间 -> YYYY-MM-DD HH:MM 显示。"""
    return iso.replace("T", " ")[:16] if iso else ""


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("BackupApp - 应用配置备份")
        self.resize(1280, 800)
        self.setMinimumSize(860, 560)
        self._workers: list = []
        self._app_id: str | None = None
        self._plans: list[BackupPlan] = []

        self._build_toolbar()
        self._build_central()
        self._build_statusbar()

        self.refresh_apps()
        self._load_log_tail()
        self.sched_group.refresh_status()

    # ---------- 构建 ----------

    _APP_DESC = "应用配置与数据备份工具（便携，跨平台）"
    _GITHUB_URL = "https://github.com/muxinxy/BackupApp"

    def _about(self):
        from PySide6.QtWidgets import QDialog, QLabel, QPushButton, QVBoxLayout
        dlg = QDialog(self)
        dlg.setWindowTitle("关于 BackupApp")
        lay = QVBoxLayout(dlg)
        lay.addWidget(QLabel(f"<h3>BackupApp</h3>"))
        lay.addWidget(QLabel(f"<b>{self._APP_DESC}</b>"))
        lay.addWidget(QLabel(f"版本 {__version__}"))
        link = QLabel(f'<a href="{self._GITHUB_URL}">{self._GITHUB_URL}</a>')
        link.setOpenExternalLinks(True)
        lay.addWidget(link)
        ok = QPushButton("确定")
        ok.clicked.connect(dlg.accept)
        lay.addWidget(ok)
        dlg.exec()

    def _build_toolbar(self):
        tb = QToolBar("主工具栏")
        tb.setMovable(False)
        self.addToolBar(tb)
        self.act_backup_all = QAction("立即备份全部", self)
        self.act_backup_all.triggered.connect(self._backup_all)
        self.act_import = QAction("导入", self)
        self.act_import.triggered.connect(self._import_app)
        self.act_export_all = QAction("导出全部", self)
        self.act_export_all.triggered.connect(self._export_all)
        self.act_self_backup = QAction("自身备份设置", self)
        self.act_self_backup.triggered.connect(self._self_backup_dialog)
        self.act_self_backup_now = QAction("备份自身", self)
        self.act_self_backup_now.triggered.connect(self._self_backup_now)
        self.act_self_backup_files = QAction("备份文件", self)
        self.act_self_backup_files.triggered.connect(self._self_backup_files_dialog)
        self.act_script = QAction("批量生成脚本", self)
        self.act_script.triggered.connect(self._scripts_batch)
        self.act_task_batch_reg = QAction("批量注册任务", self)
        self.act_task_batch_reg.triggered.connect(self._task_batch_register)
        self.act_task_batch_unreg = QAction("批量取消注册任务", self)
        self.act_task_batch_unreg.triggered.connect(self._task_batch_unregister)
        self.act_about = QAction("关于", self)
        self.act_about.triggered.connect(self._about)

        # 按钮按功能分组，每组用 QFrame 框起来
        self._tool_group(tb, [
            self.act_backup_all,
        ])
        self._tool_group(tb, [
            self.act_import, self.act_export_all,
        ])
        self._tool_group(tb, [
            self.act_task_batch_reg, self.act_task_batch_unreg,
        ])
        self._tool_group(tb, [
            self.act_script,
        ])
        self._tool_group(tb, [
            self.act_self_backup, self.act_self_backup_now,
            self.act_self_backup_files,
        ])
        tb.addSeparator()
        # 主题切换（明亮/暗黑/跟随系统），选择持久化到 settings
        self.theme_combo = QComboBox()
        self.theme_combo.addItem("明亮", "light")
        self.theme_combo.addItem("暗黑", "dark")
        self.theme_combo.addItem("跟随系统", "system")
        self.theme_combo.setCurrentIndex(max(0, self.theme_combo.findData(
            store.load_settings().general.theme)))
        self.theme_combo.currentIndexChanged.connect(self._theme_changed)
        tb.addWidget(QLabel(" 主题:"))
        tb.addWidget(self.theme_combo)
        # 关于放工具栏最后
        tb.addSeparator()
        self._tool_group(tb, [self.act_about])

    def _tool_group(self, tb: QToolBar, actions: list[QAction]):
        """把一组 QAction 放进带边框的 QFrame 再挂到工具栏。"""
        from PySide6.QtWidgets import QFrame, QHBoxLayout, QToolButton
        frame = QFrame()
        frame.setObjectName("toolGroup")
        lay = QHBoxLayout(frame)
        lay.setContentsMargins(4, 2, 4, 2)
        lay.setSpacing(2)
        for act in actions:
            btn = QToolButton()
            btn.setDefaultAction(act)
            btn.setToolButtonStyle(Qt.ToolButtonTextOnly)
            lay.addWidget(btn)
        tb.addWidget(frame)

    def _theme_changed(self):
        from PySide6.QtWidgets import QApplication
        from . import theme
        name = self.theme_combo.currentData()
        cfg = store.load_settings()
        cfg.general.theme = name
        store.save_settings(cfg)
        theme.apply_theme(QApplication.instance(), name)

    def _build_central(self):
        splitter_v = QSplitter(Qt.Vertical)
        splitter_h = QSplitter(Qt.Horizontal)

        # 左：应用列表
        left = QWidget()
        lay = QVBoxLayout(left)
        self.app_list = QListWidget()
        self.app_list.currentItemChanged.connect(self._on_app_selected)
        lay.addWidget(self.app_list, 1)
        row = QHBoxLayout()
        self.btn_app_new = QPushButton("新增")
        self.btn_app_edit = QPushButton("编辑")
        self.btn_app_del = QPushButton("删除")
        self.btn_app_import = QPushButton("导入")
        self.btn_app_export = QPushButton("导出")
        self.btn_app_new.clicked.connect(self._app_new)
        self.btn_app_edit.clicked.connect(self._app_edit)
        self.btn_app_del.clicked.connect(self._app_delete)
        self.btn_app_import.clicked.connect(self._import_app)
        self.btn_app_export.clicked.connect(self._export_selected)
        for b in (self.btn_app_new, self.btn_app_edit, self.btn_app_del,
                  self.btn_app_import, self.btn_app_export):
            row.addWidget(b)
        lay.addLayout(row)

        # 右：计划表格
        right = QWidget()
        lay = QVBoxLayout(right)
        self.plan_table = QTableWidget(0, len(_PLAN_COLS))
        self.plan_table.setHorizontalHeaderLabels(_PLAN_COLS)
        self.plan_table.setSelectionBehavior(QTableWidget.SelectRows)
        self.plan_table.setSelectionMode(QTableWidget.SingleSelection)
        self.plan_table.setAlternatingRowColors(True)
        header = self.plan_table.horizontalHeader()
        # 源/目的两列平铺剩余宽度；窄列固定宽度
        header.setSectionResizeMode(0, QHeaderView.Fixed)
        self.plan_table.setColumnWidth(0, 48)
        for col, (mode, w) in {
                1: (QHeaderView.Interactive, 130),   # 名称
                2: (QHeaderView.Stretch, 0),         # 源
                3: (QHeaderView.Stretch, 0),         # 目的
                4: (QHeaderView.Fixed, 90),          # 保留
                5: (QHeaderView.Fixed, 70),          # 格式
                6: (QHeaderView.Fixed, 115),         # 创建时间
                7: (QHeaderView.Fixed, 115),         # 修改时间
                8: (QHeaderView.Interactive, 140),   # 状态
                9: (QHeaderView.Fixed, 70),          # 任务
        }.items():
            header.setSectionResizeMode(col, mode)
            if w:
                self.plan_table.setColumnWidth(col, w)
        self.plan_table.doubleClicked.connect(self._plan_edit)
        self.plan_table.itemSelectionChanged.connect(self.refresh_plan_task_state)
        lay.addWidget(self.plan_table, 1)
        row = QHBoxLayout()
        self.btn_backup = QPushButton("备份")
        self.btn_restore = QPushButton("恢复")
        self.btn_plan_new = QPushButton("新增计划")
        self.btn_plan_edit = QPushButton("编辑")
        self.btn_plan_script = QPushButton("生成脚本")
        self.btn_plan_task = QPushButton("注册计划任务")
        self.btn_plan_del = QPushButton("删除计划")
        self.btn_backup.setObjectName("success")
        self.btn_restore.setObjectName("warning")
        self.btn_plan_del.setObjectName("danger")
        self.btn_app_del.setObjectName("danger")
        self.btn_backup.clicked.connect(self._plan_backup)
        self.btn_restore.clicked.connect(self._plan_restore)
        self.btn_plan_new.clicked.connect(self._plan_new)
        self.btn_plan_edit.clicked.connect(self._plan_edit)
        self.btn_plan_script.clicked.connect(self._script_dialog)
        self.btn_plan_task.clicked.connect(self._plan_task_toggle)
        self.btn_plan_del.clicked.connect(self._plan_delete)
        for b in (self.btn_backup, self.btn_restore, self.btn_plan_new,
                  self.btn_plan_edit, self.btn_plan_script, self.btn_plan_task,
                  self.btn_plan_del):
            row.addWidget(b)
        lay.addLayout(row)

        splitter_h.addWidget(left)
        splitter_h.addWidget(right)
        splitter_h.setStretchFactor(0, 1)
        splitter_h.setStretchFactor(1, 3)

        self.log_view = QPlainTextEdit()
        self.log_view.setReadOnly(True)
        self.log_view.setMaximumBlockCount(5000)

        splitter_v.addWidget(splitter_h)
        splitter_v.addWidget(self.log_view)
        splitter_v.setStretchFactor(0, 3)
        splitter_v.setStretchFactor(1, 1)
        splitter_v.setChildrenCollapsible(False)

        # 调度器放主布局顶部（不随工具栏宽度裁切），全窗口宽度自适应
        central = QWidget()
        lay = QVBoxLayout(central)
        lay.setContentsMargins(8, 6, 8, 6)
        lay.setSpacing(6)
        self.sched_group = SchedulerGroup(central)
        lay.addWidget(self.sched_group)
        lay.addWidget(splitter_v, 1)
        self.setCentralWidget(central)

    def _build_statusbar(self):
        self.status_label = QLabel("就绪")
        self.statusBar().addWidget(self.status_label)
        # 备份/恢复进行中的忙碌动画（不定进度条）
        self.busy_bar = QProgressBar()
        self.busy_bar.setRange(0, 0)
        self.busy_bar.setFixedWidth(120)
        self.busy_bar.setTextVisible(False)
        self.busy_bar.hide()
        self.statusBar().addPermanentWidget(self.busy_bar)

    # ---------- 数据刷新 ----------

    def refresh_apps(self, select_id: str | None = None):
        self.app_list.blockSignals(True)
        self.app_list.clear()
        for app in store.list_apps():
            item = QListWidgetItem(f"{app.name}  ({app.id})")
            item.setData(Qt.UserRole, app.id)
            # 悬停显示完整应用信息（名称/ID/备注/路径数）
            tip = f"{app.name}  ({app.id})"
            extra = []
            if app.note:
                extra.append(app.note)
            if app.config_paths:
                extra.append(f"配置 {len(app.config_paths)} 项")
            if app.data_paths:
                extra.append(f"数据 {len(app.data_paths)} 项")
            if extra:
                tip += "\n" + "\n".join(extra)
            item.setToolTip(tip)
            self.app_list.addItem(item)
        self.app_list.blockSignals(False)
        if select_id:
            for i in range(self.app_list.count()):
                if self.app_list.item(i).data(Qt.UserRole) == select_id:
                    self.app_list.setCurrentRow(i)
                    break
        elif self.app_list.count():
            self.app_list.setCurrentRow(0)
        else:
            self._app_id = None
            self._plans = []
            self._render_plans()

    def _on_app_selected(self, cur, _prev):
        self._app_id = cur.data(Qt.UserRole) if cur else None
        self.refresh_plans()

    def refresh_plans(self):
        self._plans = []
        if self._app_id:
            app = store.load_app(self._app_id)
            if app:
                self._plans = app.plans
        # 一次系统查询批量获取已注册的计划任务（避免每行一次子进程）
        self._registered_plans = set()
        if self._app_id:
            try:
                from .. import scheduler as sched
                reg = sched.registered_plan_tasks()
                self._registered_plans = {
                    p.id for p in self._plans
                    if sched.plan_task_name(self._app_id, p.id) in reg}
            except Exception:
                pass
        self._render_plans()
        self.refresh_plan_task_state()

    def refresh_plan_task_state(self):
        """按选中计划的注册状态更新按钮（用缓存，不起子进程）。"""
        plan = self._selected_plan()
        if not plan or not self._app_id:
            self.btn_plan_task.setEnabled(True)
            self.btn_plan_task.setText("注册计划任务")
            return
        self.btn_plan_task.setText(
            "取消注册任务" if plan.id in self._registered_plans else "注册计划任务")

    def _render_plans(self):
        self.plan_table.setRowCount(len(self._plans))
        for row, plan in enumerate(self._plans):
            cb = QCheckBox()
            cb.setChecked(plan.enabled)
            cb.setToolTip("启用/停用该计划")
            cb.toggled.connect(lambda checked, r=row: self._toggle_plan(r, checked))
            wrap = QWidget()
            wl = QHBoxLayout(wrap)
            wl.setContentsMargins(0, 0, 0, 0)
            wl.setAlignment(Qt.AlignCenter)
            wl.addWidget(cb)
            self.plan_table.setCellWidget(row, 0, wrap)
            src = plan.sources[0] if plan.sources else ""
            if len(plan.sources) > 1:
                src += f" (+{len(plan.sources) - 1})"
            fmt = plan.format if plan.compress else "目录"
            # 保留列：N份/N天 + 月/年快照标记
            ret = f"{plan.retention}{'份' if plan.retention_unit == 'count' else '天'}"
            ret_extra = []
            if plan.keep_monthly:
                ret_extra.append("月")
            if plan.keep_yearly:
                ret_extra.append("年")
            if ret_extra:
                ret += "/" + "/".join(ret_extra)
            # 状态列：中文值 + 带年份时间；未运行置灰
            raw = plan.last_result or ""
            color_kind = None
            if not raw:
                status = "未运行"
            else:
                base = raw.split(":", 1)[0].strip()
                label = {"ok": "成功", "error": "失败",
                         "restored": "已恢复"}.get(base, raw)
                ts = _fmt_ts(plan.last_run_at)
                status = f"{label} @ {ts}" if ts else label
                color_kind = {"ok": "ok", "error": "error",
                              "restored": "info"}.get(base, "warn")
            # 任务列：系统任务注册状态
            registered = plan.id in self._registered_plans
            task_text = "已注册" if registered else "未注册"
            try:
                from .. import scheduler as sched
                task_name = sched.plan_task_name(self._app_id or "", plan.id)
            except Exception:
                task_name = ""
            values = [plan.name, src, plan.destination,
                      ret, fmt, _fmt_ts(plan.created_at), _fmt_ts(plan.updated_at),
                      status, task_text]
            # 悬停显示完整内容：源路径列展示全部源路径，其余列展示单元格全文
            tips = [plan.name,
                    "\n".join(plan.sources) if plan.sources else "",
                    plan.destination,
                    values[3], values[4], values[5], values[6], status, task_name]
            for col, v in enumerate(values, start=1):
                item = QTableWidgetItem(v)
                item.setFlags(item.flags() & ~Qt.ItemIsEditable)
                tip = tips[col - 1]
                if tip:
                    item.setToolTip(tip)
                if col == len(_PLAN_COLS) - 1:  # 任务列着色
                    from . import theme
                    item.setForeground(QBrush(theme.status_color("ok")
                                              if registered else QColor("#9aa4b1")))
                elif col == len(_PLAN_COLS) - 2:  # 状态列着色
                    from . import theme
                    if color_kind:
                        item.setForeground(QBrush(theme.status_color(color_kind)))
                    else:
                        item.setForeground(QBrush(QColor("#9aa4b1")))
                self.plan_table.setItem(row, col, item)

    def _toggle_plan(self, row: int, checked: bool):
        if not self._app_id or row >= len(self._plans):
            return
        plan = self._plans[row]
        plan.enabled = checked
        app = store.load_app(self._app_id)
        if app:
            for p in app.plans:
                if p.id == plan.id:
                    p.enabled = checked
            store.save_app(app)

    # ---------- 应用操作 ----------

    def _app_new(self):
        dlg = AppDialog(parent=self)
        if dlg.exec() == QDialog.Accepted:
            app = dlg.app_config()
            store.save_app(app)
            self._log(f"新增应用: {app.id}")
            self.refresh_apps(select_id=app.id)

    def _app_edit(self):
        if not self._app_id:
            return
        app = store.load_app(self._app_id)
        if not app:
            return
        dlg = AppDialog(app=app, parent=self)
        if dlg.exec() == QDialog.Accepted:
            edited = dlg.app_config()
            app.name = edited.name
            app.vendor = edited.vendor
            app.version = edited.version
            app.note = edited.note
            app.config_paths = edited.config_paths
            app.data_paths = edited.data_paths
            store.save_app(app)
            self._log(f"应用已更新: {app.id}")
            self.refresh_apps(select_id=app.id)

    def _plan_task_toggle(self):
        """注册/取消注册选中计划的系统任务（按当前状态切换）。"""
        from .. import scheduler as sched
        plan = self._selected_plan()
        if not plan or not self._app_id:
            QMessageBox.information(self, "提示", "请先选择一个计划")
            return
        cfg = store.load_settings()
        if sched.plan_status(cfg, self._app_id, plan.id) == "registered":
            err = sched.plan_uninstall(self._app_id, plan.id)
            if err:
                QMessageBox.warning(self, "计划任务", f"取消注册失败：{err}")
            else:
                self._log(f"已取消注册计划任务: {self._app_id}/{plan.id}")
        else:
            err = sched.plan_install(cfg, self._app_id, plan.id)
            if err:
                QMessageBox.warning(self, "计划任务", f"注册失败：{err}")
            else:
                self._log(f"已注册计划任务: {self._app_id}/{plan.id}")
        self.refresh_plans()  # 刷新表格任务列与按钮状态

    def _task_batch_register(self):
        """批量注册所有已启用计划的系统任务。"""
        from .. import scheduler as sched
        cfg = store.load_settings()
        plans = [(a.id, p) for a in store.list_apps() for p in a.plans if p.enabled]
        if not plans:
            QMessageBox.information(self, "批量注册任务", "没有已启用的计划")
            return
        reg = sched.registered_plan_tasks()
        ok = fail = 0
        for app_id, p in plans:
            if sched.plan_task_name(app_id, p.id) in reg:
                continue
            err = sched.plan_install(cfg, app_id, p.id)
            if err:
                fail += 1
                self._log(f"注册失败 {app_id}/{p.id}: {err}")
            else:
                ok += 1
        self._log(f"批量注册任务完成：新增 {ok} 个，失败 {fail} 个")
        if fail:
            QMessageBox.warning(self, "批量注册任务", f"{fail} 个计划注册失败，详见日志")
        self.refresh_apps()

    def _task_batch_unregister(self):
        """批量取消注册所有已启用计划的系统任务。"""
        from .. import scheduler as sched
        plans = [(a.id, p) for a in store.list_apps() for p in a.plans if p.enabled]
        if not plans:
            QMessageBox.information(self, "批量取消注册任务", "没有已启用的计划")
            return
        reg = sched.registered_plan_tasks()
        ok = fail = 0
        for app_id, p in plans:
            if sched.plan_task_name(app_id, p.id) not in reg:
                continue
            err = sched.plan_uninstall(app_id, p.id)
            if err:
                fail += 1
                self._log(f"取消注册失败 {app_id}/{p.id}: {err}")
            else:
                ok += 1
        self._log(f"批量取消注册任务完成：取消 {ok} 个，失败 {fail} 个")
        if fail:
            QMessageBox.warning(self, "批量取消注册任务", f"{fail} 个计划取消注册失败，详见日志")
        self.refresh_apps()

    def _app_delete(self):
        if not self._app_id:
            return
        app_id = self._app_id
        app = store.load_app(app_id)
        if not app:
            return
        ret = QMessageBox.question(self, "删除应用",
                                   f"确定删除应用 {app_id}？\n（不会删除已生成的备份）")
        if ret == QMessageBox.Yes:
            # 顺带取消该应用全部计划的系统任务
            from .. import scheduler as sched
            for p in app.plans:
                err = sched.plan_uninstall(app_id, p.id)
                if err:
                    self._log(f"取消计划任务失败 {app_id}/{p.id}: {err}")
            store.delete_app(app_id)
            self._log(f"删除应用: {app_id}")
            self.refresh_apps()

    def _import_app(self):
        path, _ = QFileDialog.getOpenFileName(self, "导入应用配置", "",
                                              "配置 (*.json *.zip)")
        if not path:
            return
        from PySide6.QtWidgets import QCheckBox, QDialog, QDialogButtonBox, QFormLayout, QLineEdit
        dlg = QDialog(self)
        dlg.setWindowTitle("导入选项")
        lay = QFormLayout(dlg)
        is_zip = path.lower().endswith(".zip")
        cb_overwrite = QCheckBox("覆盖同 ID 的应用")
        cb_overwrite.setChecked(True)
        lay.addRow(cb_overwrite)
        pw = None
        if is_zip:
            cb_settings = QCheckBox("恢复全局设置（自身备份配置/主题等）")
            cb_settings.setChecked(True)
            lay.addRow(cb_settings)
            pw = QLineEdit()
            pw.setEchoMode(QLineEdit.Password)
            pw.setPlaceholderText("加密导出则需输入密码")
            lay.addRow("密码", pw)
        btns = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        btns.accepted.connect(dlg.accept)
        btns.rejected.connect(dlg.reject)
        lay.addRow(btns)
        if dlg.exec() != QDialog.Accepted:
            return
        try:
            ids = importexport.import_(
                path, overwrite=cb_overwrite.isChecked(),
                password=pw.text() if pw else "",
                import_settings=cb_settings.isChecked() if is_zip else True)
            self._log(f"导入成功: {', '.join(ids) if ids else '（无新应用）'}")
            self.refresh_apps(select_id=ids[0] if ids else None)
        except Exception as e:
            QMessageBox.critical(self, "导入失败", str(e))

    def _export_selected(self):
        if not self._app_id:
            return
        stamp = datetime.now().strftime("%Y%m%d_%H%M")
        path, _ = QFileDialog.getSaveFileName(self, "导出应用配置",
                                              f"{self._app_id}_{stamp}.json",
                                              "JSON (*.json)")
        if not path:
            return
        app = store.load_app(self._app_id)
        if app:
            importexport.write_one(app, path)
            self._log(f"导出 {app.id} -> {path}")

    def _export_all(self):
        stamp = datetime.now().strftime("%Y%m%d_%H%M")
        path, _ = QFileDialog.getSaveFileName(self, "导出全部应用配置",
                                              f"backupapp_export_{stamp}.zip",
                                              "ZIP (*.zip)")
        if not path:
            return
        from PySide6.QtWidgets import QCheckBox, QDialog, QDialogButtonBox, QFormLayout, QLineEdit
        dlg = QDialog(self)
        dlg.setWindowTitle("导出选项")
        lay = QFormLayout(dlg)
        cb_encrypt = QCheckBox("加密压缩包（AES）")
        lay.addRow(cb_encrypt)
        pw = QLineEdit()
        pw.setEchoMode(QLineEdit.Password)
        pw.setEnabled(False)
        pw.setPlaceholderText("导出密码")
        lay.addRow("密码", pw)
        cb_encrypt.toggled.connect(pw.setEnabled)
        btns = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        btns.accepted.connect(dlg.accept)
        btns.rejected.connect(dlg.reject)
        lay.addRow(btns)
        if dlg.exec() != QDialog.Accepted:
            return
        password = pw.text() if cb_encrypt.isChecked() else ""
        try:
            ids = importexport.export_all(path, password=password)
            self._log(f"导出 {len(ids)} 个应用 -> {path}"
                      + ("（已加密）" if password else ""))
        except Exception as e:
            QMessageBox.critical(self, "导出失败", str(e))

    # ---------- 计划操作 ----------

    def _selected_plan(self) -> BackupPlan | None:
        row = self.plan_table.currentRow()
        if 0 <= row < len(self._plans):
            return self._plans[row]
        return None

    def _plan_new(self):
        if not self._app_id:
            QMessageBox.information(self, "提示", "请先选择一个应用")
            return
        app = store.load_app(self._app_id)
        if not app:
            return
        dlg = PlanDialog(app, parent=self)
        if dlg.exec() == QDialog.Accepted:
            plan = dlg.plan()
            if app.get_plan(plan.id):
                QMessageBox.warning(self, "ID 冲突", f"计划 {plan.id} 已存在")
                return
            app.plans.append(plan)
            store.save_app(app)
            self._log(f"新增计划: {app.id}/{plan.id}")
            self.refresh_plans()

    def _plan_edit(self, *_):
        if not self._app_id:
            return
        plan = self._selected_plan()
        if not plan:
            return
        app = store.load_app(self._app_id)
        if not app:
            return
        from .. import scheduler as sched
        old_id = plan.id
        was_registered = sched.plan_status(store.load_settings(), self._app_id,
                                           old_id) == "registered"
        dlg = PlanDialog(app, plan=plan, parent=self)
        if dlg.exec() == QDialog.Accepted:
            dlg.plan()
            # 对话框直接改写 self._plans 中的对象；app 是新加载的，须原位替换后保存
            app.plans = [plan if p.id == old_id else p for p in app.plans]
            store.save_app(app)
            self._log(f"计划已更新: {app.id}/{plan.id}")
            if was_registered:
                if plan.id != old_id:
                    # ID 变更：旧任务指向已不存在的计划，自动取消注册
                    err = sched.plan_uninstall(self._app_id, old_id)
                    if err:
                        self._log(f"取消旧计划任务失败 {self._app_id}/{old_id}: {err}")
                # 已注册任务按新排期/ID 重新注册
                err = sched.plan_install(store.load_settings(), self._app_id, plan.id)
                if err:
                    self._log(f"更新计划任务失败 {self._app_id}/{plan.id}: {err}")
            self.refresh_plans()

    def _plan_delete(self):
        if not self._app_id:
            return
        plan = self._selected_plan()
        if not plan:
            return
        ret = QMessageBox.question(self, "删除计划",
                                   f"确定删除计划 {self._app_id}/{plan.id}？")
        if ret == QMessageBox.Yes:
            # 先取消注册该计划的系统任务，避免残留任务反复报"计划不存在"
            from .. import scheduler as sched
            err = sched.plan_uninstall(self._app_id, plan.id)
            if err:
                self._log(f"取消计划任务失败 {self._app_id}/{plan.id}: {err}")
            app = store.load_app(self._app_id)
            if app:
                app.plans = [p for p in app.plans if p.id != plan.id]
                store.save_app(app)
                self._log(f"删除计划: {app.id}/{plan.id}")
                self.refresh_plans()

    def _plan_backup(self):
        plan = self._selected_plan()
        if not plan or not self._app_id:
            QMessageBox.information(self, "提示", "请先选择一个计划")
            return
        key = f"{self._app_id}/{plan.id}"
        self._run_worker(f"备份 {key}", lambda: __import__(
            "backupapp.engine.backup", fromlist=["run_plan"]).run_plan(key),
            BackupWorker)

    def _backup_all(self):
        from ..engine import backup as bk
        self._run_worker("备份全部", bk.run_all, BackupWorker)

    def _plan_restore(self):
        plan = self._selected_plan()
        if not plan or not self._app_id:
            QMessageBox.information(self, "提示", "请先选择一个计划")
            return
        from ..engine import paths as epaths, retention
        dest = epaths.expand(plan.destination)
        entries = retention.list_entries(dest, self._app_id)
        if not entries:
            QMessageBox.information(
                self, "恢复", f"{dest} 下没有 {self._app_id} 的备份")
            return
        snaps = [retention.snapshot_of(e) for e in entries]
        # 自定义对话框：备份列表下拉可一次显示多项
        dlg = QDialog(self)
        dlg.setWindowTitle("选择备份")
        combo = QComboBox()
        combo.addItems(snaps)
        combo.setMaxVisibleItems(20)
        combo.setMinimumWidth(340)
        combo.setCurrentIndex(0)
        lay = QVBoxLayout(dlg)
        lay.addWidget(QLabel("选择要恢复的备份:"))
        lay.addWidget(combo)
        btns = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        btns.accepted.connect(dlg.accept)
        btns.rejected.connect(dlg.reject)
        lay.addWidget(btns)
        if dlg.exec() != QDialog.Accepted:
            return
        snap = combo.currentText()
        src = plan.sources[0] if plan.sources else "源路径"
        mb = QMessageBox(self)
        mb.setWindowTitle("恢复")
        mb.setIcon(QMessageBox.Question)
        mb.setText(f"将从备份 {snap} 恢复 {src}。")
        cb = QCheckBox("恢复前先备份当前配置/数据")
        cb.setChecked(True)
        mb.setCheckBox(cb)
        mb.setStandardButtons(QMessageBox.Ok | QMessageBox.Cancel)
        mb.exec()
        if mb.clickedButton() is not mb.button(QMessageBox.Ok):
            return
        prebak = cb.isChecked()
        key = f"{self._app_id}/{plan.id}"

        def _do():
            from ..engine import backup as bk, restore as rs
            if prebak:
                bk.run_plan(key)  # 先备份当前状态
            return rs.restore_plan(key, snap)

        self._run_worker(f"恢复 {key}", _do, RestoreWorker)

    def _run_worker(self, label: str, fn, worker_cls):
        if self._workers:
            return
        self._log(f"—— {label} 开始 ——")
        self._set_busy(True)
        self.status_label.setText(f"{label} 进行中…")
        self.busy_bar.show()
        w = worker_cls(fn, self)
        w.result.connect(self._on_worker_result)
        w.finished_all.connect(lambda ok, total, lb=label: self._on_worker_done(ok, total, lb))
        w.finished.connect(self._on_worker_finished)
        self._workers.append(w)
        w.start()

    def _on_worker_result(self, plan_key: str, ok: bool, msg: str):
        self._log(f"[{'OK ' if ok else 'FAIL'}] {plan_key}: {msg}")

    def _on_worker_done(self, ok: int, total: int, label: str):
        self._log(f"—— {label} 完成：{ok}/{total} 成功 ——")
        self.refresh_plans()
        self.sched_group.refresh_status()
        self.status_label.setText("完成" if ok == total else f"完成 {ok}/{total}")

    def _on_worker_finished(self):
        if self._workers:
            self._workers.pop()
        self._set_busy(False)
        self.busy_bar.hide()

    def _set_busy(self, busy: bool):
        for w in (self.act_backup_all, self.act_import, self.act_export_all,
                  self.act_self_backup, self.act_self_backup_now, self.act_script,
                  self.act_task_batch_reg, self.act_task_batch_unreg,
                  self.btn_app_new, self.btn_app_edit, self.btn_app_del,
                  self.btn_app_import, self.btn_app_export, self.btn_backup,
                  self.btn_restore, self.btn_plan_new, self.btn_plan_edit,
                  self.btn_plan_script, self.btn_plan_task, self.btn_plan_del):
            w.setEnabled(not busy)
        self.sched_group.setEnabled(not busy)

    # ---------- 其它 ----------

    def _self_backup_dialog(self):
        SelfBackupDialog(self).exec()

    def _self_backup_files_dialog(self):
        dlg = SelfBackupFilesDialog(self)
        dlg.restored.connect(self._on_self_restored)
        dlg.exec()

    def _on_self_restored(self):
        """自身备份恢复/删除后刷新应用列表与计划表格（无需重启）。"""
        self.refresh_apps()
        self.refresh_plans()
        self._log("自身备份数据已变更，界面已刷新")

    def _self_backup_now(self):
        from ..protocols.runner import run_self_backup
        self._run_worker("自身备份", run_self_backup, BackupWorker)

    def _script_dialog(self):
        """生成单个计划（选中）的备份/恢复一体脚本。"""
        plan = self._selected_plan()
        if not plan or not self._app_id:
            QMessageBox.information(self, "提示", "请先选择一个计划")
            return
        app = store.load_app(self._app_id)
        if not app:
            return
        from ..scripts import generator
        dlg = QDialog(self)
        dlg.setWindowTitle("生成脚本")
        flavor = QComboBox()
        flavor.addItem("Windows PowerShell (ps1)", "ps1")
        flavor.addItem("Windows 批处理 (bat)", "bat")
        flavor.addItem("Linux shell (sh)", "sh")
        form = QFormLayout(dlg)
        form.addRow("平台", flavor)
        form.addRow("", QLabel("脚本含备份与恢复功能，支持交互与 -y 静默运行"))
        btns = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        form.addRow(btns)

        def do_save():
            path, _ = QFileDialog.getSaveFileName(
                dlg, "保存脚本",
                f"{app.id}_{plan.id}.{flavor.currentData()}",
                "脚本 (*.*)")
            if not path:
                return
            content = generator.generate(app, plan, flavor.currentData())
            generator.write_script(path, content)
            self._log(f"脚本 -> {path}")
            dlg.accept()

        btns.accepted.connect(do_save)
        btns.rejected.connect(dlg.reject)
        dlg.exec()

    def _scripts_batch(self):
        """批量生成所有启用计划的备份/恢复一体脚本。"""
        plans = [(a, p) for a in store.list_apps() for p in a.plans if p.enabled]
        if not plans:
            QMessageBox.information(self, "提示", "没有启用的计划")
            return
        from ..scripts import generator
        dlg = QDialog(self)
        dlg.setWindowTitle("批量生成脚本")
        flavor = QComboBox()
        flavor.addItem("Windows PowerShell (ps1)", "ps1")
        flavor.addItem("Windows 批处理 (bat)", "bat")
        flavor.addItem("Linux shell (sh)", "sh")
        form = QFormLayout(dlg)
        form.addRow("", QLabel(f"将为 {len(plans)} 个启用计划各生成一个脚本"))
        form.addRow("平台", flavor)
        form.addRow("", QLabel("脚本含备份与恢复功能，支持交互与 -y 静默运行"))
        btns = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        form.addRow(btns)

        def do_save():
            outdir = QFileDialog.getExistingDirectory(dlg, "选择保存目录")
            if not outdir:
                return
            n = 0
            for a, p in plans:
                path = os.path.join(outdir, f"{a.id}_{p.id}.{flavor.currentData()}")
                generator.write_script(path, generator.generate(a, p, flavor.currentData()))
                n += 1
            self._log(f"生成 {n} 个脚本 -> {outdir}")
            dlg.accept()

        btns.accepted.connect(do_save)
        btns.rejected.connect(dlg.reject)
        dlg.exec()

    def _load_log_tail(self):
        log_path = os.path.join(store.logs_dir(), "backup.log")
        try:
            with open(log_path, "r", encoding="utf-8") as f:
                lines = f.readlines()[-200:]
            self.log_view.setPlainText("".join(lines))
        except OSError:
            pass

    def _log(self, text: str):
        self.log_view.appendPlainText(text)
