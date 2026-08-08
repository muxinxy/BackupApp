"""明亮/暗黑主题（Fusion + QSS），支持跟随系统，提供状态色。

切换：apply_theme(app, "light"|"dark"|"system")；current 记录生效主题，
main_window 的状态列颜色按它取 status_color()。
"""

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor

current = "light"

_COMMON = """
* {
    font-family: "Segoe UI", "Microsoft YaHei UI", "PingFang SC", sans-serif;
    font-size: 10pt;
}
QToolBar {
    spacing: 2px;
    padding: 2px 6px;
}
QToolButton {
    border: none;
    border-radius: 6px;
    padding: 3px 8px;
}
QGroupBox {
    border-radius: 10px;
    margin-top: 14px;
    padding: 14px 12px 12px 12px;
    font-weight: 600;
}
QGroupBox::title {
    subcontrol-origin: margin;
    left: 14px;
    padding: 0 4px;
}
QListWidget, QTableWidget, QPlainTextEdit, QLineEdit, QComboBox,
QSpinBox, QTimeEdit {
    border-radius: 6px;
    padding: 5px 8px;
    selection-color: #ffffff;
}
QListWidget:focus, QTableWidget:focus, QPlainTextEdit:focus,
QLineEdit:focus, QComboBox:focus, QSpinBox:focus, QTimeEdit:focus {
    border-width: 2px;
    padding: 4px 7px;
}
QHeaderView::section {
    border: none;
    border-bottom: 1px solid;
    border-right: 1px solid;
    padding: 8px 8px;
    font-weight: 600;
}
QPushButton {
    border-radius: 8px;
    padding: 6px 16px;
}
QPushButton#primary, QPushButton#success, QPushButton#warning,
QPushButton#danger {
    border: none;
    font-weight: 600;
    color: #ffffff;
}
QCheckBox { spacing: 6px; }
QStatusBar {
    border-top: 1px solid;
}
QSplitter::handle:horizontal { width: 4px; }
QSplitter::handle:vertical { height: 4px; }
QListWidget::item {
    padding: 6px 8px;
    border-radius: 6px;
    margin: 1px 2px;
}
QScrollBar:vertical { background: transparent; width: 10px; }
QScrollBar::handle:vertical { border-radius: 5px; min-height: 30px; }
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0; }
QScrollBar:horizontal { background: transparent; height: 10px; }
QScrollBar::handle:horizontal { border-radius: 5px; min-width: 30px; }
QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal { width: 0; }
QComboBox::drop-down { border: none; width: 26px; }
QSpinBox::up-button, QSpinBox::down-button {
    width: 18px;
    border: none;
    border-left: 1px solid palette(mid);
    background: transparent;
}
QSpinBox::up-button:hover, QSpinBox::down-button:hover {
    background: rgba(127, 140, 160, 0.25);
}
QSpinBox::up-button:pressed, QSpinBox::down-button:pressed {
    background: rgba(127, 140, 160, 0.4);
}
QSpinBox::up-arrow, QSpinBox::down-arrow {
    image: none;
    width: 0;
    height: 0;
}
QSpinBox::up-arrow {
    border-left: 4px solid transparent;
    border-right: 4px solid transparent;
    border-bottom: 5px solid #475569;
}
QSpinBox::down-arrow {
    border-left: 4px solid transparent;
    border-right: 4px solid transparent;
    border-top: 5px solid #475569;
}
"""

LIGHT = _COMMON + """
* { color: #1e293b; }
QMainWindow, QDialog { background: #eef2f7; }
QToolBar {
    background: #ffffff;
    border-bottom: 1px solid #dde3ec;
}
QToolButton { color: #334155; }
QToolButton:hover { background: #e8eef8; }
QToolButton:pressed { background: #dbe4f2; }
QGroupBox {
    background: #ffffff;
    border: 1px solid #dde3ec;
}
QGroupBox::title { color: #475569; }
QListWidget, QTableWidget, QPlainTextEdit, QLineEdit, QComboBox,
QSpinBox, QTimeEdit {
    background: #ffffff;
    border: 1px solid #d5dbe6;
    selection-background-color: #2563eb;
    placeholder-text-color: #9aa4b1;
}
QListWidget:focus, QTableWidget:focus, QPlainTextEdit:focus,
QLineEdit:focus, QComboBox:focus, QSpinBox:focus, QTimeEdit:focus {
    border: 2px solid #2563eb;
}
QComboBox QAbstractItemView {
    background: #ffffff;
    border: 1px solid #cfd8e4;
    border-radius: 6px;
    padding: 4px;
    outline: none;
    selection-background-color: #2563eb;
    selection-color: #ffffff;
}
QTableWidget {
    gridline-color: #e8edf5;
    alternate-background-color: #f6f8fc;
}
QHeaderView::section {
    background: #f1f5fb;
    border-bottom: 1px solid #dde3ec;
    border-right: 1px solid #e8edf5;
    color: #475569;
}
QPushButton {
    background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                                stop:0 #f7f9fc, stop:1 #e8edf5);
    border: 1px solid #cfd8e4;
    color: #1e293b;
}
QPushButton:hover {
    background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                                stop:0 #fdfefe, stop:1 #dde5f0);
    border-color: #93a6bd;
}
QPushButton:pressed { background: #cdd8e6; }
QPushButton:disabled { color: #9aa4b1; background: #f0f2f6; border-color: #e2e6ec; }
QPushButton:focus { border: 2px solid #93b4f5; padding: 5px 15px; }
QPushButton#primary {
    background: qlineargradient(x1:0, y1:0, x2:1, y2:1,
                                stop:0 #3b82f6, stop:1 #2563eb);
}
QPushButton#primary:hover { background: #2f6fe0; }
QPushButton#primary:disabled { background: #a5c4f5; color: #eef4ff; }
QPushButton#success {
    background: qlineargradient(x1:0, y1:0, x2:1, y2:1,
                                stop:0 #22c55e, stop:1 #16a34a);
}
QPushButton#success:hover { background: #16a34a; }
QPushButton#success:disabled { background: #a7d9bc; }
QPushButton#warning {
    background: qlineargradient(x1:0, y1:0, x2:1, y2:1,
                                stop:0 #f59e0b, stop:1 #d97706);
}
QPushButton#warning:hover { background: #d97706; }
QPushButton#warning:disabled { background: #e5c690; }
QPushButton#danger {
    background: qlineargradient(x1:0, y1:0, x2:1, y2:1,
                                stop:0 #f87171, stop:1 #dc2626);
}
QPushButton#danger:hover { background: #dc2626; }
QPushButton#danger:disabled { background: #e9b3b3; color: #fde8e8; }
QStatusBar { background: #ffffff; border-top: 1px solid #dde3ec; color: #475569; }
QSplitter::handle { background: #e8edf5; }
QListWidget::item:selected { background: #dbeafe; color: #1e40af; }
QListWidget::item:hover { background: #f1f5fb; }
QMessageBox, QFileDialog { background: #eef2f7; }
QScrollBar::handle:vertical, QScrollBar::handle:horizontal { background: #c9d2e0; }
"""

DARK = _COMMON + """
* { color: #e2e8f0; }
QMainWindow, QDialog { background: #0f172a; }
QToolBar {
    background: #1e293b;
    border-bottom: 1px solid #334155;
}
QToolButton { color: #cbd5e1; }
QToolButton:hover { background: #334155; }
QToolButton:pressed { background: #3b4758; }
QGroupBox {
    background: #1e293b;
    border: 1px solid #334155;
}
QGroupBox::title { color: #94a3b8; }
QListWidget, QTableWidget, QPlainTextEdit, QLineEdit, QComboBox,
QSpinBox, QTimeEdit {
    background: #0f172a;
    border: 1px solid #334155;
    selection-background-color: #2563eb;
    placeholder-text-color: #64748b;
}
QListWidget:focus, QTableWidget:focus, QPlainTextEdit:focus,
QLineEdit:focus, QComboBox:focus, QSpinBox:focus, QTimeEdit:focus {
    border: 2px solid #3b82f6;
}
QComboBox QAbstractItemView {
    background: #1e293b;
    border: 1px solid #475569;
    border-radius: 6px;
    padding: 4px;
    outline: none;
    color: #e2e8f0;
    selection-background-color: #2563eb;
    selection-color: #ffffff;
}
QTableWidget {
    gridline-color: #263449;
    alternate-background-color: #16233a;
}
QHeaderView::section {
    background: #1e293b;
    border-bottom: 1px solid #334155;
    border-right: 1px solid #263449;
    color: #94a3b8;
}
QPushButton {
    background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                                stop:0 #3b4758, stop:1 #334155);
    border: 1px solid #475569;
    color: #e2e8f0;
}
QPushButton:hover {
    background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                                stop:0 #475569, stop:1 #3b4758);
    border-color: #5b6b83;
}
QPushButton:pressed { background: #475569; }
QPushButton:disabled { color: #64748b; background: #1e293b; border-color: #334155; }
QPushButton:focus { border: 2px solid #3b82f6; padding: 5px 15px; }
QPushButton#primary {
    background: qlineargradient(x1:0, y1:0, x2:1, y2:1,
                                stop:0 #3b82f6, stop:1 #2563eb);
}
QPushButton#primary:hover { background: #3b82f6; }
QPushButton#primary:disabled { background: #274a7a; color: #7d9cc7; }
QPushButton#success {
    background: qlineargradient(x1:0, y1:0, x2:1, y2:1,
                                stop:0 #22c55e, stop:1 #16a34a);
}
QPushButton#success:hover { background: #22c55e; }
QPushButton#success:disabled { background: #1d5035; color: #8fc7a5; }
QPushButton#warning {
    background: qlineargradient(x1:0, y1:0, x2:1, y2:1,
                                stop:0 #f59e0b, stop:1 #d97706);
}
QPushButton#warning:hover { background: #f59e0b; }
QPushButton#warning:disabled { background: #5c4316; color: #d9b98a; }
QPushButton#danger {
    background: qlineargradient(x1:0, y1:0, x2:1, y2:1,
                                stop:0 #f87171, stop:1 #dc2626);
}
QPushButton#danger:hover { background: #dc2626; }
QPushButton#danger:disabled { background: #5c2626; color: #e9b3b3; }
QStatusBar { background: #1e293b; border-top: 1px solid #334155; color: #94a3b8; }
QSplitter::handle { background: #1a2740; }
QListWidget::item:selected { background: #1e3a5f; color: #93c5fd; }
QListWidget::item:hover { background: #263449; }
QMessageBox, QFileDialog { background: #0f172a; }
QScrollBar::handle:vertical, QScrollBar::handle:horizontal { background: #475569; }
QSpinBox::up-arrow { border-bottom-color: #94a3b8; }
QSpinBox::down-arrow { border-top-color: #94a3b8; }
QSpinBox::up-button:hover, QSpinBox::down-button:hover {
    background: rgba(148, 163, 184, 0.2);
}
QSpinBox::up-button:pressed, QSpinBox::down-button:pressed {
    background: rgba(148, 163, 184, 0.35);
}
"""


def detect_dark(app) -> bool:
    try:
        return app.styleHints().colorScheme() == Qt.ColorScheme.Dark
    except Exception:
        return False


def apply_theme(app, name: str) -> None:
    """name: light | dark | system。更新全局样式与 current。"""
    global current
    if name == "system":
        name = "dark" if detect_dark(app) else "light"
    current = name
    app.setStyle("Fusion")
    app.setStyleSheet(DARK if name == "dark" else LIGHT)


def status_color(kind: str) -> QColor:
    pal = {
        "ok": ("#16a34a", "#4ade80"),
        "error": ("#dc2626", "#f87171"),
        "info": ("#2563eb", "#60a5fa"),
        "warn": ("#d97706", "#fbbf24"),
    }[kind]
    return QColor(pal[1] if current == "dark" else pal[0])
