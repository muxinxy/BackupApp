"""主窗口：应用列表 + 计划表格 + 日志面板 + 工具栏（调度/自身备份/脚本）。"""

import os
import sys
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
from ..i18n import _
from ..storage import importexport, store
from .app_dialog import AppDialog
from .plan_dialog import PlanDialog
from .settings_dialogs import SchedulerGroup, SelfBackupDialog, SelfBackupFilesDialog
from .workers import BackupWorker, RestoreWorker

def _plan_cols() -> list[str]:
    return [_("启用"), _("名称"), _("源"), _("目的"), _("保留"), _("格式"),
            _("创建时间"), _("修改时间"), _("状态"), _("任务")]


def _fmt_ts(iso: str | None) -> str:
    """ISO 时间 -> YYYY-MM-DD HH:MM 显示。"""
    return iso.replace("T", " ")[:16] if iso else ""


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle(_("BackupApp - 应用配置备份"))
        self.resize(1280, 800)
        self.setMinimumSize(860, 560)
        self._workers: list = []
        self._app_id: str | None = None
        self._plans: list[BackupPlan] = []
        # 已注册计划任务集合：由后台 SchedRefreshWorker 维护，界面只读缓存
        self._registered_plans: set[str] = set()
        self._sched_worker = None
        self._sched_pending = False

        self._build_toolbar()
        self._build_central()
        self._build_statusbar()
        # 全局计划任务状态由后台查询刷新（schtasks 冷查询可达数秒，不能堵 UI 线程）
        self.sched_group.after_change = self._sched_refresh_async

        self.refresh_apps()
        self._load_log_tail()
        self._sched_refresh_async()

    def closeEvent(self, event):
        """退出时收尾后台调度查询线程，避免 QThread destroyed while running。"""
        if self._sched_worker is not None and self._sched_worker.isRunning():
            if not self._sched_worker.wait(3000):
                self._sched_worker.terminate()
                self._sched_worker.wait(500)
        super().closeEvent(event)

    # ---------- 构建 ----------

    def _app_desc(self) -> str:
        return _("应用配置与数据备份工具（便携，跨平台）")
    _GITHUB_URL = "https://github.com/muxinxy/BackupApp"

    def _about(self):
        from PySide6.QtWidgets import QDialog, QLabel, QPushButton, QVBoxLayout
        dlg = QDialog(self)
        dlg.setWindowTitle(_("关于 BackupApp"))
        lay = QVBoxLayout(dlg)
        lay.addWidget(QLabel(f"<h3>BackupApp</h3>"))
        lay.addWidget(QLabel(f"<b>{self._app_desc()}</b>"))
        lay.addWidget(QLabel(_("版本 {version}").format(version=__version__)))
        link = QLabel(f'<a href="{self._GITHUB_URL}">{self._GITHUB_URL}</a>')
        link.setOpenExternalLinks(True)
        lay.addWidget(link)
        ok = QPushButton(_("确定"))
        ok.clicked.connect(dlg.accept)
        lay.addWidget(ok)
        dlg.exec()

    def _build_toolbar(self):
        tb = QToolBar(_("主工具栏"))
        tb.setMovable(False)
        self.addToolBar(tb)
        self.act_backup_all = QAction(_("立即备份全部"), self)
        self.act_backup_all.triggered.connect(self._backup_all)
        self.act_import = QAction(_("导入"), self)
        self.act_import.triggered.connect(self._import_app)
        self.act_export_all = QAction(_("导出全部"), self)
        self.act_export_all.triggered.connect(self._export_all)
        self.act_self_backup = QAction(_("自身备份设置"), self)
        self.act_self_backup.triggered.connect(self._self_backup_dialog)
        self.act_self_backup_now = QAction(_("备份自身"), self)
        self.act_self_backup_now.triggered.connect(self._self_backup_now)
        self.act_self_backup_files = QAction(_("备份文件"), self)
        self.act_self_backup_files.triggered.connect(self._self_backup_files_dialog)
        self.act_script = QAction(_("批量生成脚本"), self)
        self.act_script.triggered.connect(self._scripts_batch)
        self.act_task_batch_reg = QAction(_("批量注册任务"), self)
        self.act_task_batch_reg.triggered.connect(self._task_batch_register)
        self.act_task_batch_unreg = QAction(_("批量取消注册任务"), self)
        self.act_task_batch_unreg.triggered.connect(self._task_batch_unregister)
        self.act_about = QAction(_("关于"), self)
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
        self.theme_combo.addItem(_("明亮"), "light")
        self.theme_combo.addItem(_("暗黑"), "dark")
        self.theme_combo.addItem(_("跟随系统"), "system")
        self.theme_combo.setCurrentIndex(max(0, self.theme_combo.findData(
            store.load_settings().general.theme)))
        self.theme_combo.currentIndexChanged.connect(self._theme_changed)
        tb.addWidget(QLabel(_(" 主题:")))
        tb.addWidget(self.theme_combo)
        # 语言切换（跟随系统/简体中文/English），持久化到 settings，重启后生效
        self.lang_combo = QComboBox()
        self.lang_combo.addItem(_("跟随系统"), "auto")
        self.lang_combo.addItem(_("简体中文"), "zh-CN")
        self.lang_combo.addItem("English", "en")
        self.lang_combo.setCurrentIndex(max(0, self.lang_combo.findData(
            store.load_settings().general.language)))
        self.lang_combo.currentIndexChanged.connect(self._lang_changed)
        tb.addWidget(QLabel(_("语言:")))
        tb.addWidget(self.lang_combo)
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

    def _lang_changed(self):
        from PySide6.QtCore import QProcess
        from PySide6.QtWidgets import QApplication
        cfg = store.load_settings()
        cfg.general.language = self.lang_combo.currentData()
        store.save_settings(cfg)
        # 自动重启：保存后立即以新语言重启（原样保留 --data-dir 等启动参数）
        QProcess.startDetached(sys.executable, sys.argv)
        QApplication.quit()

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
        self.btn_app_new = QPushButton(_("新增"))
        self.btn_app_edit = QPushButton(_("编辑"))
        self.btn_app_del = QPushButton(_("删除"))
        self.btn_app_import = QPushButton(_("导入"))
        self.btn_app_export = QPushButton(_("导出"))
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
        self.plan_table = QTableWidget(0, len(_plan_cols()))
        self.plan_table.setHorizontalHeaderLabels(_plan_cols())
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
        self.btn_backup = QPushButton(_("备份"))
        self.btn_restore = QPushButton(_("恢复"))
        self.btn_plan_new = QPushButton(_("新增计划"))
        self.btn_plan_edit = QPushButton(_("编辑"))
        self.btn_plan_script = QPushButton(_("生成脚本"))
        self.btn_plan_task = QPushButton(_("注册计划任务"))
        self.btn_plan_del = QPushButton(_("删除计划"))
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
        self.status_label = QLabel(_("就绪"))
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
                extra.append(_("配置 {n} 项").format(n=len(app.config_paths)))
            if app.data_paths:
                extra.append(_("数据 {n} 项").format(n=len(app.data_paths)))
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
        self._render_plans()
        self.refresh_plan_task_state()
        # 注册状态查询在后台执行，完成后只刷新任务列，避免阻塞 UI 线程
        self._sched_refresh_async()

    # ---------- 后台刷新系统任务注册状态 ----------

    def _sched_refresh_async(self):
        """后台查询已注册计划任务 + 全局任务状态（单飞，防重复起子进程）。"""
        if self._sched_worker is not None:
            self._sched_pending = True
            return
        from .workers import SchedRefreshWorker
        w = SchedRefreshWorker(store.load_settings(), self)
        self._sched_worker = w
        w.done.connect(self._on_sched_refreshed)
        w.finished.connect(w.deleteLater)
        w.start()

    def _on_sched_refreshed(self, registered, st):
        self._sched_worker = None
        if registered is not None:
            self._registered_plans = registered
            self._refresh_task_columns()
            self.refresh_plan_task_state()
        if st is not None:
            self.sched_group.set_state(st)
        if self._sched_pending:
            self._sched_pending = False
            self._sched_refresh_async()

    def _refresh_task_columns(self):
        """后台刷新完成后更新计划表格的任务列（避免整表重建丢选择/滚动）。"""
        if not self._app_id:
            return
        for row in range(len(self._plans)):
            plan = self._plans[row]
            registered = plan.id in self._registered_plans
            task_text = _("已注册") if registered else _("未注册")
            item = self.plan_table.item(row, len(_plan_cols()) - 1)
            if item is None:
                continue
            item.setText(task_text)
            try:
                from .. import scheduler as sched
                task_name = sched.plan_task_name(self._app_id or "", plan.id)
            except Exception:
                task_name = ""
            from . import theme
            item.setForeground(QBrush(theme.status_color("ok")
                                      if registered else QColor("#9aa4b1")))
            item.setToolTip(task_name)

    def refresh_plan_task_state(self):
        """按选中计划的注册状态更新按钮（用缓存，不起子进程）。"""
        plan = self._selected_plan()
        if not plan or not self._app_id:
            self.btn_plan_task.setEnabled(True)
            self.btn_plan_task.setText(_("注册计划任务"))
            return
        self.btn_plan_task.setText(
            _("取消注册任务") if plan.id in self._registered_plans else _("注册计划任务"))

    def _render_plans(self):
        self.plan_table.setRowCount(len(self._plans))
        for row, plan in enumerate(self._plans):
            cb = QCheckBox()
            cb.setChecked(plan.enabled)
            cb.setToolTip(_("启用/停用该计划"))
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
            fmt = plan.format if plan.compress else _("目录")
            # 保留列：N份/N天 + 月/年快照标记
            ret = _("{n}{unit}").format(
                n=plan.retention,
                unit=_("份") if plan.retention_unit == "count" else _("天"))
            ret_extra = []
            if plan.keep_monthly:
                ret_extra.append(_("月"))
            if plan.keep_yearly:
                ret_extra.append(_("年"))
            if ret_extra:
                ret += "/" + "/".join(ret_extra)
            # 状态列：中文值 + 带年份时间；未运行置灰
            raw = plan.last_result or ""
            color_kind = None
            if not raw:
                status = _("未运行")
            else:
                base = raw.split(":", 1)[0].strip()
                label = {"ok": _("成功"), "error": _("失败"),
                         "restored": _("已恢复")}.get(base, raw)
                ts = _fmt_ts(plan.last_run_at)
                status = _("{label} @ {ts}").format(label=label, ts=ts) if ts else label
                color_kind = {"ok": "ok", "error": "error",
                              "restored": "info"}.get(base, "warn")
            # 任务列：系统任务注册状态
            registered = plan.id in self._registered_plans
            task_text = _("已注册") if registered else _("未注册")
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
                if col == len(_plan_cols()) - 1:  # 任务列着色
                    from . import theme
                    item.setForeground(QBrush(theme.status_color("ok")
                                              if registered else QColor("#9aa4b1")))
                elif col == len(_plan_cols()) - 2:  # 状态列着色
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
            self._log(_("新增应用: {app_id}").format(app_id=app.id))
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
            self._log(_("应用已更新: {app_id}").format(app_id=app.id))
            self.refresh_apps(select_id=app.id)

    def _plan_task_toggle(self):
        """注册/取消注册选中计划的系统任务（按当前状态切换）。"""
        from .. import scheduler as sched
        plan = self._selected_plan()
        if not plan or not self._app_id:
            QMessageBox.information(self, _("提示"), _("请先选择一个计划"))
            return
        cfg = store.load_settings()
        # 用后台缓存判断注册状态，避免 UI 线程同步查 schtasks（冷查询可达数秒）
        if plan.id in self._registered_plans:
            err = sched.plan_uninstall(self._app_id, plan.id)
            if err:
                QMessageBox.warning(self, _("计划任务"),
                                    _("取消注册失败：{err}").format(err=err))
            else:
                self._log(_("已取消注册计划任务: {app_id}/{plan_id}").format(
                    app_id=self._app_id, plan_id=plan.id))
        else:
            err = sched.plan_install(cfg, self._app_id, plan.id)
            if err:
                QMessageBox.warning(self, _("计划任务"),
                                    _("注册失败：{err}").format(err=err))
            else:
                self._log(_("已注册计划任务: {app_id}/{plan_id}").format(
                    app_id=self._app_id, plan_id=plan.id))
        self.refresh_plans()  # 刷新表格任务列与按钮状态

    def _task_batch_register(self):
        """批量注册所有已启用计划的系统任务（后台执行，不冻结界面）。"""
        if not any(p.enabled for a in store.list_apps() for p in a.plans):
            QMessageBox.information(self, _("批量注册任务"), _("没有已启用的计划"))
            return
        self._run_batch_worker(_("批量注册任务"), True)

    def _task_batch_unregister(self):
        """批量取消注册所有已启用计划的系统任务（后台执行）。"""
        if not any(p.enabled for a in store.list_apps() for p in a.plans):
            QMessageBox.information(self, _("批量取消注册任务"), _("没有已启用的计划"))
            return
        self._run_batch_worker(_("批量取消注册任务"), False)

    def _run_batch_worker(self, label: str, register: bool):
        if self._workers:
            return
        from .workers import BatchTaskWorker
        self._log(_("—— {label} 开始 ——").format(label=label))
        self._set_busy(True)
        self.status_label.setText(_("{label} 进行中…").format(label=label))
        self.busy_bar.show()
        w = BatchTaskWorker(register, self)
        w.result.connect(self._on_worker_result)
        w.finished_all.connect(lambda ok, total, lb=label: self._on_batch_done(ok, total, lb))
        w.finished.connect(self._on_worker_finished)
        self._workers.append(w)
        w.start()

    def _on_batch_done(self, ok: int, total: int, label: str):
        fail = total - ok
        self._log(_("—— {label} 完成：成功 {ok} 个，失败 {fail} 个 ——").format(
            label=label, ok=ok, fail=fail))
        if fail:
            QMessageBox.warning(self, label,
                                _("{fail} 个计划操作失败，详见日志").format(fail=fail))
        self.refresh_apps()  # 刷新任务列与注册状态（后台查询）
        self.status_label.setText(
            _("完成") if not fail else _("完成，{fail} 个失败").format(fail=fail))

    def _app_delete(self):
        if not self._app_id:
            return
        app_id = self._app_id
        app = store.load_app(app_id)
        if not app:
            return
        ret = QMessageBox.question(self, _("删除应用"),
                                   _("确定删除应用 {app_id}？\n（不会删除已生成的备份）")
                                   .format(app_id=app_id))
        if ret == QMessageBox.Yes:
            # 顺带取消该应用全部计划的系统任务
            from .. import scheduler as sched
            for p in app.plans:
                err = sched.plan_uninstall(app_id, p.id)
                if err:
                    self._log(_("取消计划任务失败 {app_id}/{plan_id}: {err}").format(
                        app_id=app_id, plan_id=p.id, err=err))
            store.delete_app(app_id)
            self._log(_("删除应用: {app_id}").format(app_id=app_id))
            self.refresh_apps()

    def _import_app(self):
        path, _filt = QFileDialog.getOpenFileName(self, _("导入应用配置"), "",
                                                  _("配置 (*.json *.zip)"))
        if not path:
            return
        from PySide6.QtWidgets import QCheckBox, QDialog, QDialogButtonBox, QFormLayout, QLineEdit
        dlg = QDialog(self)
        dlg.setWindowTitle(_("导入选项"))
        lay = QFormLayout(dlg)
        is_zip = path.lower().endswith(".zip")
        cb_overwrite = QCheckBox(_("覆盖同 ID 的应用"))
        cb_overwrite.setChecked(True)
        lay.addRow(cb_overwrite)
        pw = None
        if is_zip:
            cb_settings = QCheckBox(_("恢复全局设置（自身备份配置/主题等）"))
            cb_settings.setChecked(True)
            lay.addRow(cb_settings)
            pw = QLineEdit()
            pw.setEchoMode(QLineEdit.Password)
            pw.setPlaceholderText(_("加密导出则需输入密码"))
            lay.addRow(_("密码"), pw)
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
            self._log(_("导入成功: {detail}").format(
                detail=", ".join(ids) if ids else _("（无新应用）")))
            self.refresh_apps(select_id=ids[0] if ids else None)
        except Exception as e:
            QMessageBox.critical(self, _("导入失败"), str(e))

    def _export_selected(self):
        if not self._app_id:
            return
        stamp = datetime.now().strftime("%Y%m%d_%H%M")
        path, _filt = QFileDialog.getSaveFileName(self, _("导出应用配置"),
                                                  f"{self._app_id}_{stamp}.json",
                                                  _("JSON (*.json)"))
        if not path:
            return
        app = store.load_app(self._app_id)
        if app:
            importexport.write_one(app, path)
            self._log(_("导出 {app_id} -> {path}").format(app_id=app.id, path=path))

    def _export_all(self):
        stamp = datetime.now().strftime("%Y%m%d_%H%M")
        path, _filt = QFileDialog.getSaveFileName(self, _("导出全部应用配置"),
                                                  f"backupapp_export_{stamp}.zip",
                                                  _("ZIP (*.zip)"))
        if not path:
            return
        from PySide6.QtWidgets import QCheckBox, QDialog, QDialogButtonBox, QFormLayout, QLineEdit
        dlg = QDialog(self)
        dlg.setWindowTitle(_("导出选项"))
        lay = QFormLayout(dlg)
        cb_encrypt = QCheckBox(_("加密压缩包（AES）"))
        lay.addRow(cb_encrypt)
        pw = QLineEdit()
        pw.setEchoMode(QLineEdit.Password)
        pw.setEnabled(False)
        pw.setPlaceholderText(_("导出密码"))
        lay.addRow(_("密码"), pw)
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
            self._log(_("导出 {n} 个应用 -> {path}").format(n=len(ids), path=path)
                      + (_("（已加密）") if password else ""))
        except Exception as e:
            QMessageBox.critical(self, _("导出失败"), str(e))

    # ---------- 计划操作 ----------

    def _selected_plan(self) -> BackupPlan | None:
        row = self.plan_table.currentRow()
        if 0 <= row < len(self._plans):
            return self._plans[row]
        return None

    def _plan_new(self):
        if not self._app_id:
            QMessageBox.information(self, _("提示"), _("请先选择一个应用"))
            return
        app = store.load_app(self._app_id)
        if not app:
            return
        dlg = PlanDialog(app, parent=self)
        if dlg.exec() == QDialog.Accepted:
            plan = dlg.plan()
            if app.get_plan(plan.id):
                QMessageBox.warning(self, _("ID 冲突"),
                                    _("计划 {plan_id} 已存在").format(plan_id=plan.id))
                return
            app.plans.append(plan)
            store.save_app(app)
            self._log(_("新增计划: {app_id}/{plan_id}").format(
                app_id=app.id, plan_id=plan.id))
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
        # 用后台缓存判断注册状态：同步查 schtasks 冷查询可达数秒，会卡住编辑弹窗
        was_registered = plan.id in self._registered_plans
        dlg = PlanDialog(app, plan=plan, parent=self)
        if dlg.exec() == QDialog.Accepted:
            dlg.plan()
            # 对话框直接改写 self._plans 中的对象；app 是新加载的，须原位替换后保存
            app.plans = [plan if p.id == old_id else p for p in app.plans]
            store.save_app(app)
            self._log(_("计划已更新: {app_id}/{plan_id}").format(
                app_id=app.id, plan_id=plan.id))
            if was_registered:
                if plan.id != old_id:
                    # ID 变更：旧任务指向已不存在的计划，自动取消注册
                    err = sched.plan_uninstall(self._app_id, old_id)
                    if err:
                        self._log(_("取消旧计划任务失败 {app_id}/{plan_id}: {err}").format(
                            app_id=self._app_id, plan_id=old_id, err=err))
                # 已注册任务按新排期/ID 重新注册
                err = sched.plan_install(store.load_settings(), self._app_id, plan.id)
                if err:
                    self._log(_("更新计划任务失败 {app_id}/{plan_id}: {err}").format(
                        app_id=self._app_id, plan_id=plan.id, err=err))
            self.refresh_plans()

    def _plan_delete(self):
        if not self._app_id:
            return
        plan = self._selected_plan()
        if not plan:
            return
        ret = QMessageBox.question(self, _("删除计划"),
                                   _("确定删除计划 {app_id}/{plan_id}？").format(
                                       app_id=self._app_id, plan_id=plan.id))
        if ret == QMessageBox.Yes:
            # 先取消注册该计划的系统任务，避免残留任务反复报"计划不存在"
            from .. import scheduler as sched
            err = sched.plan_uninstall(self._app_id, plan.id)
            if err:
                self._log(_("取消计划任务失败 {app_id}/{plan_id}: {err}").format(
                    app_id=self._app_id, plan_id=plan.id, err=err))
            app = store.load_app(self._app_id)
            if app:
                app.plans = [p for p in app.plans if p.id != plan.id]
                store.save_app(app)
                self._log(_("删除计划: {app_id}/{plan_id}").format(
                    app_id=app.id, plan_id=plan.id))
                self.refresh_plans()

    def _plan_backup(self):
        plan = self._selected_plan()
        if not plan or not self._app_id:
            QMessageBox.information(self, _("提示"), _("请先选择一个计划"))
            return
        key = f"{self._app_id}/{plan.id}"

        def _do(cb):
            from ..engine.backup import run_plan
            return run_plan(key, progress=cb)

        self._run_worker(_("备份 {key}").format(key=key), _do, BackupWorker)

    def _backup_all(self):
        def _do(cb):
            from ..engine.backup import run_all
            return run_all(progress=cb)

        self._run_worker(_("备份全部"), _do, BackupWorker)

    def _plan_restore(self):
        plan = self._selected_plan()
        if not plan or not self._app_id:
            QMessageBox.information(self, _("提示"), _("请先选择一个计划"))
            return
        from ..engine import paths as epaths, retention
        dest = epaths.expand(plan.destination)
        entries = retention.list_entries(dest, self._app_id)
        if not entries:
            QMessageBox.information(
                self, _("恢复"), _("{dest} 下没有 {app_id} 的备份").format(
                    dest=dest, app_id=self._app_id))
            return
        snaps = [retention.snapshot_of(e) for e in entries]
        # 自定义对话框：备份列表下拉可一次显示多项
        dlg = QDialog(self)
        dlg.setWindowTitle(_("选择备份"))
        combo = QComboBox()
        combo.addItems(snaps)
        combo.setMaxVisibleItems(20)
        combo.setMinimumWidth(340)
        combo.setCurrentIndex(0)
        lay = QVBoxLayout(dlg)
        lay.addWidget(QLabel(_("选择要恢复的备份:")))
        lay.addWidget(combo)
        btns = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        btns.accepted.connect(dlg.accept)
        btns.rejected.connect(dlg.reject)
        lay.addWidget(btns)
        if dlg.exec() != QDialog.Accepted:
            return
        snap = combo.currentText()
        src = plan.sources[0] if plan.sources else _("源路径")
        mb = QMessageBox(self)
        mb.setWindowTitle(_("恢复"))
        mb.setIcon(QMessageBox.Question)
        mb.setText(_("将从备份 {snap} 恢复 {src}。").format(snap=snap, src=src))
        cb = QCheckBox(_("恢复前先备份当前配置/数据"))
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

        self._run_worker(_("恢复 {key}").format(key=key), _do, RestoreWorker)

    def _run_worker(self, label: str, fn, worker_cls):
        if self._workers:
            return
        self._log(_("—— {label} 开始 ——").format(label=label))
        self._set_busy(True)
        self.status_label.setText(_("{label} 进行中…").format(label=label))
        self.busy_bar.show()
        w = worker_cls(fn, self)
        w.result.connect(self._on_worker_result)
        w.finished_all.connect(lambda ok, total, lb=label: self._on_worker_done(ok, total, lb))
        w.finished.connect(self._on_worker_finished)
        if hasattr(w, "progress"):
            w.progress.connect(self._log)
        self._workers.append(w)
        w.start()

    def _on_worker_result(self, plan_key: str, ok: bool, msg: str):
        self._log(f"[{'OK ' if ok else 'FAIL'}] {plan_key}: {msg}")

    def _on_worker_done(self, ok: int, total: int, label: str):
        self._log(_("—— {label} 完成：{ok}/{total} 成功 ——").format(
            label=label, ok=ok, total=total))
        self.refresh_plans()  # 内部触发后台刷新任务注册状态
        self.status_label.setText(
            _("完成") if ok == total else _("完成 {ok}/{total}").format(ok=ok, total=total))

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
        # 导航与表格也锁住，避免进行中切换应用/点计划触发刷新
        self.app_list.setEnabled(not busy)
        self.plan_table.setEnabled(not busy)
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
        self._log(_("自身备份数据已变更，界面已刷新"))

    def _self_backup_now(self):
        def _do(cb):
            from ..protocols.runner import run_self_backup
            return run_self_backup()

        self._run_worker(_("自身备份"), _do, BackupWorker)

    def _script_dialog(self):
        """生成单个计划（选中）的备份/恢复一体脚本。"""
        plan = self._selected_plan()
        if not plan or not self._app_id:
            QMessageBox.information(self, _("提示"), _("请先选择一个计划"))
            return
        app = store.load_app(self._app_id)
        if not app:
            return
        from ..scripts import generator
        dlg = QDialog(self)
        dlg.setWindowTitle(_("生成脚本"))
        flavor = QComboBox()
        flavor.addItem(_("Windows PowerShell (ps1)"), "ps1")
        flavor.addItem(_("Windows 批处理 (bat)"), "bat")
        flavor.addItem(_("Linux shell (sh)"), "sh")
        form = QFormLayout(dlg)
        form.addRow(_("平台"), flavor)
        form.addRow("", QLabel(_("脚本含备份与恢复功能，支持交互与 -y 静默运行")))
        btns = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        form.addRow(btns)

        def do_save():
            path, _filt = QFileDialog.getSaveFileName(
                dlg, _("保存脚本"),
                f"{app.id}_{plan.id}.{flavor.currentData()}",
                _("脚本 (*.*)"))
            if not path:
                return
            content = generator.generate(app, plan, flavor.currentData())
            generator.write_script(path, content)
            self._log(_("脚本 -> {path}").format(path=path))
            dlg.accept()

        btns.accepted.connect(do_save)
        btns.rejected.connect(dlg.reject)
        dlg.exec()

    def _scripts_batch(self):
        """批量生成所有启用计划的备份/恢复一体脚本。"""
        plans = [(a, p) for a in store.list_apps() for p in a.plans if p.enabled]
        if not plans:
            QMessageBox.information(self, _("提示"), _("没有启用的计划"))
            return
        from ..scripts import generator
        dlg = QDialog(self)
        dlg.setWindowTitle(_("批量生成脚本"))
        flavor = QComboBox()
        flavor.addItem(_("Windows PowerShell (ps1)"), "ps1")
        flavor.addItem(_("Windows 批处理 (bat)"), "bat")
        flavor.addItem(_("Linux shell (sh)"), "sh")
        form = QFormLayout(dlg)
        form.addRow("", QLabel(_("将为 {n} 个启用计划各生成一个脚本").format(n=len(plans))))
        form.addRow(_("平台"), flavor)
        form.addRow("", QLabel(_("脚本含备份与恢复功能，支持交互与 -y 静默运行")))
        btns = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        form.addRow(btns)

        def do_save():
            outdir = QFileDialog.getExistingDirectory(dlg, _("选择保存目录"))
            if not outdir:
                return
            n = 0
            for a, p in plans:
                path = os.path.join(outdir, f"{a.id}_{p.id}.{flavor.currentData()}")
                generator.write_script(path, generator.generate(a, p, flavor.currentData()))
                n += 1
            self._log(_("生成 {n} 个脚本 -> {outdir}").format(n=n, outdir=outdir))
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
        # 加载后直接跳到底部（setPlainText 默认停在顶部）
        sb = self.log_view.verticalScrollBar()
        sb.setValue(sb.maximum())

    def _log(self, text: str):
        self.log_view.appendPlainText(text)
        # 追加后强制滚动到底部（appendPlainText 在用户上翻过时不自动跟随）
        sb = self.log_view.verticalScrollBar()
        sb.setValue(sb.maximum())
