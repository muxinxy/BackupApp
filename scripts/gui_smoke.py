"""GUI 冒烟测试：offscreen 渲染 + 经 MainWindow 触发真实备份 worker。

用法: .venv\Scripts\python scripts\gui_smoke.py
"""

import os
import sys
import time

os.environ["QT_QPA_PLATFORM"] = "offscreen"

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from backupapp.storage import store  # noqa: E402

# 自包含：清空并用假应用初始化数据目录，避免依赖手工预置数据
smoke_data = r"C:\Users\ZengZhe\AppData\Local\Temp\opencode\backupapp_smoke\data"
smoke_src = r"C:\Users\ZengZhe\AppData\Local\Temp\opencode\backupapp_smoke\src"
smoke_dst = r"C:\Users\ZengZhe\AppData\Local\Temp\opencode\backupapp_smoke\bk"
store.set_data_root(smoke_data)
import shutil  # noqa: E402
for p in (smoke_data, smoke_src, smoke_dst):
    shutil.rmtree(p, ignore_errors=True)
os.makedirs(smoke_src, exist_ok=True)
with open(os.path.join(smoke_src, "config.ini"), "w", encoding="utf-8") as f:
    f.write("key=value")
from backupapp.model import AppConfig, BackupPlan  # noqa: E402
plan = BackupPlan(id="cfg", name="cfg", sources=[smoke_src], destination=smoke_dst)
store.save_app(AppConfig(id="testapp", name="Test App", plans=[plan]))

from PySide6.QtCore import Qt  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from backupapp.i18n import set_language  # noqa: E402
from backupapp.i18n import _  # noqa: E402

set_language("zh-CN")

app = QApplication([])
from backupapp.gui import theme  # noqa: E402

theme.apply_theme(app, "light")

from backupapp.gui.main_window import MainWindow  # noqa: E402

w = MainWindow()
w.show()
assert w.grab().save(r"C:\Users\ZengZhe\AppData\Local\Temp\opencode\gui_preview.png"), "截图失败"
print("RENDER OK")

# 选中第一个应用（testapp）及其第一个计划
assert w.app_list.count() >= 1, "应用列表为空"
w.app_list.setCurrentRow(0)
app_id = w.app_list.item(0).data(Qt.UserRole)
print(f"selected app: {app_id}, plans: {len(w._plans)}")
assert len(w._plans) >= 1, "没有计划"
w.plan_table.selectRow(0)

# 走与"备份"按钮相同的 worker 路径
w._plan_backup()
deadline = time.time() + 60
while w._workers and time.time() < deadline:
    app.processEvents()
    time.sleep(0.05)
assert not w._workers, "worker 未在超时前完成"

text = w.log_view.toPlainText()
print("--- 日志面板尾部 ---")
print(text[-500:])
assert "OK" in text and app_id in text, "日志面板未出现成功结果"
print("BACKUP VIA GUI WORKER OK")

# 界面状态刷新：计划表格应有"成功"状态（状态列 = 第 9 列，索引 8）
status_cell = w.plan_table.item(0, 8).text()
print(f"plan status cell: {status_cell!r}")
assert "成功" in status_cell, f"状态列未刷新: {status_cell!r}"

# 后台任务 worker：删除应用触发的计划任务取消必须走 TaskOpWorker 而不是
# 在 UI 线程同步调 schtasks（冷查询数秒会冻结界面）。这里 monkeypatch 掉
# scheduler 的真实调用，只验证"确实起了后台 worker 且经其完成"。
from backupapp.gui import workers as gui_workers  # noqa: E402

assert hasattr(gui_workers, "TaskOpWorker"), "TaskOpWorker 缺失"
ops_seen = []


class _FakeTaskOp(gui_workers.TaskOpWorker):
    def run(self):
        ops_seen.extend(self._ops)
        self.finished_all.emit(len(self._ops), len(self._ops))


gui_workers.TaskOpWorker = _FakeTaskOp
w._workers.clear()
w._run_task_worker([("uninstall", "testapp", "cfg")])
deadline = time.time() + 30
while w._workers and time.time() < deadline:
    app.processEvents()
    time.sleep(0.05)
assert ops_seen == [("uninstall", "testapp", "cfg")], f"后台任务未执行: {ops_seen}"
print(f"task op via background worker OK: {ops_seen}")

# 关窗收尾：模拟一个仍在运行的 worker，closeEvent 必须等它结束而不是直接销毁
from PySide6.QtCore import QThread as _QThread  # noqa: E402


class _Slow(_QThread):
    def run(self):
        time.sleep(0.3)


slow = _Slow(w)
w._workers.append(slow)
slow.start()
w.close()  # 不应抛 "QThread: Destroyed while thread is still running"
assert not slow.isRunning(), "closeEvent 未等待在途 worker"
print("closeEvent waits for in-flight workers OK")

# 后台 JobWorker 路径：导出全部应用（zip 写入 + 可能的加密）应走后台线程，
# 完成后回到主线程并留下日志，而不是阻塞 UI。
from backupapp.storage import importexport  # noqa: E402

export_path = os.path.join(r"C:\Users\ZengZhe\AppData\Local\Temp\opencode\backupapp_smoke",
                           "export_smoke.zip")
if os.path.exists(export_path):
    os.remove(export_path)
w._workers.clear()


def _do_export():
    ids = importexport.export_all(export_path)
    return ids, "export done"


w._run_job(_do_export, "{detail}", "导出失败")
deadline = time.time() + 60
while w._workers and time.time() < deadline:
    app.processEvents()
    time.sleep(0.05)
assert not w._workers, "JobWorker 未在超时前完成"
assert os.path.isfile(export_path), "后台导出未产出 zip"
assert "export done" in w.log_view.toPlainText(), "导出完成日志缺失"
print("background export job OK")

# 增量刷新：结构未变时 refresh_apps / refresh_plans 不应重建行，选中行与
# 滚动位置必须保留（备份完成、任务注册后都会触发刷新）。
w.refresh_apps()
w.plan_table.selectRow(0)
before_row = w.plan_table.currentRow()
before_sb = w.plan_table.verticalScrollBar().value()
before_id = w.app_list.currentItem().data(Qt.UserRole)
w.refresh_apps()
w.refresh_plans()
assert w.app_list.currentItem() is not None, "刷新后应用选中项丢失"
assert w.app_list.currentItem().data(Qt.UserRole) == before_id, \
    "刷新后应用选中项被改变"
assert w.plan_table.currentRow() == before_row, \
    f"刷新后计划选中行丢失: {w.plan_table.currentRow()} != {before_row}"
assert w.plan_table.verticalScrollBar().value() == before_sb, "刷新后滚动位置被重置"
assert w.plan_table.item(0, 8).text(), "增量刷新后状态列内容为空"
print(f"incremental refresh preserves selection/scroll (row={before_row})")

# 选项对话框脚手架：导入/导出的密码框初始状态必须正确
# （导入可直接填；导出需勾选"加密"后才启用），且路径可达不抛异常。
from PySide6.QtCore import QTimer  # noqa: E402
from PySide6.QtWidgets import QCheckBox as _QCB, QDialog as _QDialog  # noqa: E402
from PySide6.QtWidgets import QLineEdit as _QLE  # noqa: E402


def _capture_and_close(store_into):
    """定时器回调：抓取当前模态对话框的密码框状态并关闭它。"""
    def _run():
        for wdg in app.topLevelWidgets():
            if isinstance(wdg, _QDialog) and wdg.isVisible():
                edits = wdg.findChildren(_QLE)
                if edits:
                    store_into["pw_enabled"] = edits[0].isEnabled()
                wdg.reject()
                return
    return _run


# 导入式：密码框初始应可用
got = {}
QTimer.singleShot(50, _capture_and_close(got))
w._options_dialog("导入选项", [], password_placeholder="密码")
assert got.get("pw_enabled") is True, "导入式密码框应初始可用"

# 导出式：密码框初始禁用，勾选复选框后启用
got2 = {}
cb = _QCB("加密压缩包（AES）")


def _check_and_close():
    for wdg in app.topLevelWidgets():
        if isinstance(wdg, _QDialog) and wdg.isVisible():
            edits = wdg.findChildren(_QLE)
            got2["before"] = edits[0].isEnabled()
            cb.setChecked(True)  # 触发 toggled -> 启用密码框
            got2["after"] = edits[0].isEnabled()
            wdg.reject()
            return


QTimer.singleShot(50, _check_and_close)
w._options_dialog("导出选项", [(None, cb)], password_placeholder="导出密码",
                  password_enabled=False,
                  on_ready=lambda _d, e: cb.toggled.connect(e.setEnabled))
assert got2.get("before") is False, f"导出式密码框应初始禁用: {got2}"
assert got2.get("after") is True, f"勾选加密后密码框应启用: {got2}"
print("options dialog scaffolding OK (import enabled / export toggled)")

# 导入必须真正生效：_options_dialog 把对话框当局部变量，返回后子控件会被回收，
# 调用方若在返回后读勾选框就会抛 "Internal C++ object already deleted"（异常
# 被 Qt 槽吞掉 -> 表现成"点了没反应"）。这里驱动真实 _import_app 验证端到端。
import json as _json  # noqa: E402
from PySide6.QtWidgets import QFileDialog as _QFD  # noqa: E402

imp_src = os.path.join(r"C:\Users\ZengZhe\AppData\Local\Temp\opencode\backupapp_smoke",
                       "imported_app.json")
with open(imp_src, "w", encoding="utf-8") as f:
    _json.dump({"id": "imported1", "name": "Imported One", "vendor": "",
                "version": "", "note": "", "configPaths": [], "dataPaths": [],
                "createdAt": "", "schemaVersion": 2, "plans": []},
               f, ensure_ascii=False)

before_ids = [w.app_list.item(i).data(Qt.UserRole) for i in range(w.app_list.count())]
_orig_open = _QFD.getOpenFileName
_QFD.getOpenFileName = staticmethod(lambda *a, **k: (imp_src, "配置 (*.json *.zip)"))


def _accept_options():
    for wdg in app.topLevelWidgets():
        if isinstance(wdg, _QDialog) and wdg.isVisible():
            wdg.accept()
            return


QTimer.singleShot(120, _accept_options)
w._import_app()
deadline = time.time() + 60
while w._workers and time.time() < deadline:
    app.processEvents()
    time.sleep(0.05)
_QFD.getOpenFileName = _orig_open

after_ids = [w.app_list.item(i).data(Qt.UserRole) for i in range(w.app_list.count())]
assert "imported1" in after_ids, \
    f"导入未生效（应用列表仍是 {after_ids}，导入前 {before_ids}）"
assert os.path.isfile(store.app_path("imported1")), "导入后磁盘上没有该应用"
print(f"import actually applied OK ({before_ids} -> {after_ids})")

# 计划任务状态：_registered_plans 存的是任务名（BackupApp_<app>_<plan>），
# 不是 plan.id。直接用 plan.id 比对会恒为假 -> 一直显示"未注册"。
from backupapp import scheduler as _sched  # noqa: E402

w.refresh_apps(select_id="testapp")
w.plan_table.selectRow(0)
_plan = w._plans[0]
_task_name = _sched.plan_task_name("testapp", _plan.id)
assert _task_name != _plan.id, "测试前提：任务名应不同于 plan.id"
# 未注册时
w._registered_plans = set()
assert not w._is_plan_registered(_plan), "未注册时应判为未注册"
w.refresh_plan_task_state()
assert "注册" in w.btn_plan_task.text()
# 模拟后台查询结果：任务名在集合里 -> 应判为已注册
w._registered_plans = {_task_name}
assert w._is_plan_registered(_plan), \
    "任务名已注册时应判为已注册（按 plan.id 比对会恒为假）"
w.refresh_plan_task_state()
assert w.btn_plan_task.text() == _("取消注册任务"), \
    f"已注册时按钮应为'取消注册任务'，实际 {w.btn_plan_task.text()!r}"
# 表格任务列也应显示"已注册"
w._refresh_task_columns()
assert w.plan_table.item(0, 9).text() == _("已注册"), \
    f"任务列应显示已注册，实际 {w.plan_table.item(0, 9).text()!r}"
w._registered_plans = set()
print("plan task registration state resolves by task name OK")

# 暗黑模式下复选框指示器必须可见（Fusion 默认绘制在暗色底上对比度极低）
from backupapp.gui import theme as _theme  # noqa: E402
from PySide6.QtWidgets import QCheckBox as _QCB2, QHBoxLayout as _QHL, QWidget as _QW  # noqa: E402


def _indicator_contrast():
    """渲染复选框，统计指示器区域相对背景的最大明度差。"""
    from collections import Counter
    host = _QW()
    lay = _QHL(host)
    cbx = _QCB2("x")
    cbx.setChecked(False)
    lay.addWidget(cbx)
    host.resize(60, 30)
    host.show()
    app.processEvents()
    img = host.grab().toImage()
    px = [(img.pixelColor(x, y).red(), img.pixelColor(x, y).green(),
           img.pixelColor(x, y).blue())
          for y in range(img.height()) for x in range(min(22, img.width()))]
    bg = Counter(px).most_common(1)[0][0]
    bg_lum = 0.299 * bg[0] + 0.587 * bg[1] + 0.114 * bg[2]
    return max(abs(0.299 * r + 0.587 * g + 0.114 * b - bg_lum) for r, g, b in px)


_prev_theme = _theme.current
_theme.apply_theme(app, "dark")
dark_contrast = _indicator_contrast()
_theme.apply_theme(app, _prev_theme)
print(f"dark checkbox indicator contrast = {dark_contrast:.0f}")
assert dark_contrast >= 40, \
    f"暗黑模式复选框对比度过低（{dark_contrast:.0f}），框线看不清"

print("GUI SMOKE ALL PASS")
