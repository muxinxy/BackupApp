"""应用配置导入导出：单应用 JSON / 全部应用 zip（可加密）。

zip 内含 apps/*.json 与 settings.json（全局设置：自身备份配置/主题/调度器），
导入时按需恢复 settings 并支持覆盖策略。
"""

import json
import os
import zipfile
from datetime import datetime

from ..model import AppConfig, Settings
from . import store


def export_one(app: AppConfig) -> dict:
    return app.to_dict()


def write_one(app: AppConfig, out_path: str) -> None:
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(app.to_dict(), f, ensure_ascii=False, indent=2)


def export_all(out_path: str, password: str = "") -> list[str]:
    """全部应用 + settings.json 打包 zip，返回包含的应用 id 列表。

    password 非空时用 AES 加密（pyzipper）。
    """
    apps = store.list_apps()
    if password:
        import pyzipper
        with pyzipper.AESZipFile(out_path, "w",
                                 compression=pyzipper.ZIP_DEFLATED,
                                 encryption=pyzipper.WZ_AES) as z:
            z.setpassword(password.encode("utf-8"))
            for app in apps:
                z.writestr(f"apps/{app.id}.json",
                           json.dumps(app.to_dict(), ensure_ascii=False, indent=2))
            z.writestr("settings.json",
                       json.dumps(store.load_settings().to_dict(),
                                  ensure_ascii=False, indent=2))
    else:
        with zipfile.ZipFile(out_path, "w", zipfile.ZIP_DEFLATED) as z:
            for app in apps:
                z.writestr(f"apps/{app.id}.json",
                           json.dumps(app.to_dict(), ensure_ascii=False, indent=2))
            z.writestr("settings.json",
                       json.dumps(store.load_settings().to_dict(),
                                  ensure_ascii=False, indent=2))
    return [a.id for a in apps]


def import_(path: str, overwrite: bool = True, password: str = "",
            import_settings: bool = True) -> list[str]:
    """导入单 json 或 zip，返回导入的应用 id 列表。

    - overwrite：相同 id 应用是否覆盖（False 时跳过已存在的）
    - import_settings：zip 是否同时恢复 settings.json（自身备份配置等）
    - password：加密 zip 的解密密码
    """
    imported: list[str] = []
    if path.lower().endswith(".zip"):
        if password:
            import pyzipper
            with pyzipper.AESZipFile(path, "r") as z:
                z.setpassword(password.encode("utf-8"))
                imported = _import_zip(z, overwrite, import_settings)
        else:
            with zipfile.ZipFile(path) as z:
                imported = _import_zip(z, overwrite, import_settings)
    else:
        with open(path, "r", encoding="utf-8") as f:
            app = AppConfig.from_dict(json.load(f))
        if overwrite or not store.load_app(app.id):
            store.save_app(app)
            imported.append(app.id)
    return imported


def _import_zip(z, overwrite: bool, import_settings: bool) -> list[str]:
    imported: list[str] = []
    for name in z.namelist():
        if name == "settings.json" and import_settings:
            try:
                d = json.loads(z.read(name))
                settings = Settings.from_dict(d)
                if settings.self_backups:
                    # 合并自身备份配置：仅写入 zip 中存在的协议，不丢本地其他协议
                    cur = store.load_settings()
                    for proto, sb in settings.self_backups.items():
                        cur.self_backups[proto] = sb
                    store.save_settings(cur)
            except Exception:
                pass  # settings 损坏不阻断应用导入
        elif name.startswith("apps/") and name.endswith(".json"):
            d = json.loads(z.read(name))
            app = AppConfig.from_dict(d)
            if overwrite or not store.load_app(app.id):
                store.save_app(app)
                imported.append(app.id)
    return imported
