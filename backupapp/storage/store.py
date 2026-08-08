"""数据存储：应用 JSON、全局设置、日志目录。

数据根目录 = platformdirs.user_data_dir("BackupApp")，--portable 时 = exe 同目录 data/。
"""

import json
import os
import re

from platformdirs import user_data_dir

from ..model import AppConfig, BackupPlan, SCHEMA_VERSION, Settings

VALID_ID = re.compile(r"^[A-Za-z0-9._-]+$")

_root: str | None = None


def set_data_root(path: str | None) -> None:
    global _root
    _root = path


def data_dir() -> str:
    root = _root or user_data_dir("BackupApp", "ConfigBackup")
    for sub in ("apps", "logs", "backups"):
        os.makedirs(os.path.join(root, sub), exist_ok=True)
    return root


def apps_dir() -> str:
    p = os.path.join(data_dir(), "apps")
    os.makedirs(p, exist_ok=True)
    return p


def logs_dir() -> str:
    p = os.path.join(data_dir(), "logs")
    os.makedirs(p, exist_ok=True)
    return p


def backups_dir() -> str:
    p = os.path.join(data_dir(), "backups")
    os.makedirs(p, exist_ok=True)
    return p


def settings_path() -> str:
    return os.path.join(data_dir(), "settings.json")


def app_path(app_id: str) -> str:
    if not VALID_ID.match(app_id):
        raise ValueError(f"非法应用 id: {app_id!r}")
    return os.path.join(apps_dir(), f"{app_id}.json")


def _read_json(path: str) -> dict | None:
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except FileNotFoundError:
        return None


def _write_json(path: str, data: dict) -> None:
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


# ---- 应用 ----

def list_apps() -> list[AppConfig]:
    out = []
    for name in sorted(os.listdir(apps_dir())):
        if name.endswith(".json"):
            app = load_app(name[:-5])
            if app:
                out.append(app)
    return out


def load_app(app_id: str) -> AppConfig | None:
    d = _read_json(app_path(app_id))
    return AppConfig.from_dict(d) if d else None


def save_app(app: AppConfig) -> None:
    _write_json(app_path(app.id), app.to_dict())


def delete_app(app_id: str) -> None:
    p = app_path(app_id)
    if os.path.exists(p):
        os.remove(p)


def load_plan(app_id: str, plan_id: str) -> tuple[AppConfig, BackupPlan] | None:
    app = load_app(app_id)
    if not app:
        return None
    plan = app.get_plan(plan_id)
    return (app, plan) if plan else None


# ---- 全局设置 ----

def load_settings() -> Settings:
    d = _read_json(settings_path())
    return Settings.from_dict(d) if d else Settings.default()


def save_settings(s: Settings) -> None:
    _write_json(settings_path(), s.to_dict())
