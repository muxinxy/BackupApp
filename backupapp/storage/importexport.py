"""应用配置导入导出：单应用 JSON / 全部应用 zip。"""

import json
import os
import zipfile
from datetime import datetime

from ..model import AppConfig
from . import store


def export_one(app: AppConfig) -> dict:
    return app.to_dict()


def write_one(app: AppConfig, out_path: str) -> None:
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(app.to_dict(), f, ensure_ascii=False, indent=2)


def export_all(out_path: str) -> list[str]:
    """全部应用 + settings.json 打包 zip，返回包含的应用 id 列表。"""
    apps = store.list_apps()
    with zipfile.ZipFile(out_path, "w", zipfile.ZIP_DEFLATED) as z:
        for app in apps:
            z.writestr(f"apps/{app.id}.json", json.dumps(app.to_dict(), ensure_ascii=False, indent=2))
        z.writestr("settings.json", json.dumps(store.load_settings().to_dict(), ensure_ascii=False, indent=2))
    return [a.id for a in apps]


def import_(path: str) -> list[str]:
    """导入单 json 或 zip，按 id 覆盖写入，返回导入的应用 id 列表。"""
    imported: list[str] = []
    if path.lower().endswith(".zip"):
        with zipfile.ZipFile(path) as z:
            for name in z.namelist():
                if name.startswith("apps/") and name.endswith(".json"):
                    d = json.loads(z.read(name))
                    app = AppConfig.from_dict(d)
                    store.save_app(app)
                    imported.append(app.id)
    else:
        with open(path, "r", encoding="utf-8") as f:
            app = AppConfig.from_dict(json.load(f))
        store.save_app(app)
        imported.append(app.id)
    return imported
