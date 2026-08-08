"""新增/编辑应用对话框。"""

from PySide6.QtWidgets import (QDialog, QDialogButtonBox, QFormLayout, QLineEdit,
                               QMessageBox, QVBoxLayout)

from ..model import AppConfig
from ..storage import store
from .widgets import PathListEditor


class AppDialog(QDialog):
    def __init__(self, app: AppConfig | None = None, parent=None):
        super().__init__(parent)
        self.setWindowTitle("编辑应用" if app else "新增应用")
        self.setMinimumWidth(520)
        self._app = app

        self._id = QLineEdit(app.id if app else "")
        self._id.setPlaceholderText("唯一标识，如 vscode、com.example.app")
        if app:
            self._id.setEnabled(False)  # id 是文件名主键，不允许改
        self._name = QLineEdit(app.name if app else "")
        self._vendor = QLineEdit(app.vendor if app else "")
        self._version = QLineEdit(app.version if app else "")
        self._note = QLineEdit(app.note if app else "")
        self._config_paths = PathListEditor()
        self._config_paths.set_paths(app.config_paths if app else [])
        self._data_paths = PathListEditor()
        self._data_paths.set_paths(app.data_paths if app else [])

        # 名称默认跟随 ID（仅在名称为空时同步）
        if not app:
            self._id.textChanged.connect(
                lambda t: self._name.setText(t) if not self._name.text() else None)

        form = QFormLayout()
        form.addRow("ID", self._id)
        form.addRow("名称", self._name)
        form.addRow("厂商", self._vendor)
        form.addRow("版本", self._version)
        form.addRow("备注", self._note)
        form.addRow("配置路径", self._config_paths)
        form.addRow("数据路径", self._data_paths)
        btns = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        btns.accepted.connect(self._accept)
        btns.rejected.connect(self.reject)
        lay = QVBoxLayout(self)
        lay.addLayout(form)
        lay.addWidget(btns)

    def _accept(self):
        app_id = self._id.text().strip()
        name = self._name.text().strip()
        if not app_id or not name:
            QMessageBox.warning(self, "输入不完整", "ID 和名称不能为空")
            return
        if not self._app and store.load_app(app_id):
            QMessageBox.warning(self, "ID 已存在", f"应用 {app_id} 已存在")
            return
        self.accept()

    def app_config(self) -> AppConfig:
        return AppConfig(
            id=self._id.text().strip(),
            name=self._name.text().strip(),
            vendor=self._vendor.text().strip(),
            version=self._version.text().strip(),
            note=self._note.text().strip(),
            config_paths=self._config_paths.paths(),
            data_paths=self._data_paths.paths(),
            created_at=self._app.created_at if self._app else "",
            plans=self._app.plans if self._app else [],
        )
