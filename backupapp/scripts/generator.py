"""生成自包含的备份/恢复脚本（ps1/bat/sh）。

参数以 {{TOKEN}} 形式内嵌到脚本（embedConfig=true）。
- 备份脚本支持多源路径；sh 的 zip 格式支持密码（tar.gz 不支持）
- bat/ps1 无标准库加密 zip：密码仅由应用本体执行时生效（脚本头有注释说明）
- 恢复脚本以第一个源路径为恢复目标
"""

import os
from importlib.resources import files


def _template(kind: str, flavor: str) -> str:
    return (files("backupapp.scripts") / "templates" / f"{kind}.{flavor}.tpl")\
        .read_text(encoding="utf-8")


def _base(p: str) -> str:
    return os.path.basename(p.rstrip("/\\")) or p


def _dq(s: str, flavor: str) -> str:
    if flavor == "ps1":
        return '"' + s.replace("`", "``").replace('"', '""').replace("$", "`$") + '"'
    if flavor == "sh":
        return '"' + (s.replace("\\", "\\\\").replace('"', '\\"')
                      .replace("$", "\\$")) + '"'
    return '"' + s + '"'  # bat：%VAR% 由运行时展开，属有意保留


def _sh_q(s: str) -> str:
    return "'" + s.replace("'", "'\\''") + "'"


def _backup_tokens(plan, flavor: str) -> dict[str, str]:
    srcs = plan.sources or []
    if flavor == "ps1":
        return {"SRCS_PS": "\n".join(f"  {_dq(s, 'ps1')}," for s in srcs)}
    if flavor == "sh":
        archive_args = " ".join(
            f'-C {_dq(os.path.dirname(s), "sh")} {_dq(_base(s), "sh")}' for s in srcs)
        return {"ARCHIVE_ARGS": archive_args,
                "SRC_PATHS": " ".join(_dq(s, "sh") for s in srcs),
                "PW": _sh_q(plan.password)}
    # bat
    archive_args = " ".join(
        f'-C {_dq(os.path.dirname(s), "bat")} {_dq(_base(s), "bat")}' for s in srcs)
    lines = []
    for s in srcs:
        lines.append(f'    robocopy {_dq(s, "bat")} "%DEST%\\%APP%_%TS%\\{_base(s)}" /E /R:2 /W:2 >nul')
        lines.append("    if errorlevel 8 exit /b 1")
    return {"ARCHIVE_ARGS": archive_args, "COPY_BLOCK": "\n".join(lines)}


def generate(app, plan, kind: str, flavor: str) -> str:
    t = _template(kind, flavor)
    vals = {
        "APP": app.id,
        "PLAN": f"{app.id}/{plan.id}",
        "SRC": plan.sources[0] if plan.sources else "",
        "DEST": plan.destination,
        "FMT": plan.format,
        "COMPRESS": "1" if plan.compress else "0",
        "KEEP": str(plan.retention),
        "MONTHLY": "1" if plan.keep_monthly else "0",
    }
    if kind == "backup":
        vals.update(_backup_tokens(plan, flavor))
    for k, v in vals.items():
        t = t.replace("{{" + k + "}}", v)
    return t
