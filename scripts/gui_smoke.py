"""GUI 冒烟测试：offscreen 渲染 + 经 MainWindow 触发真实备份 worker。

用法: .venv\Scripts\python scripts\gui_smoke.py
"""

import os
import sys
import time

os.environ["QT_QPA_PLATFORM"] = "offscreen"

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from backupapp.storage import store  # noqa: E402

store.set_data_root(r"C:\Users\ZengZhe\AppData\Local\Temp\opencode\backupapp_smoke\data")

from PySide6.QtCore import Qt  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

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

print("GUI SMOKE ALL PASS")
