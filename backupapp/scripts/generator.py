"""生成自包含的备份+恢复一体脚本（ps1/bat/sh）。

参数以 {{TOKEN}} 形式内嵌到脚本（embedConfig=true）。
- 单脚本含 backup/restore 两个子命令，支持交互式与 -y 静默运行
- 恢复支持 --snapshot 指定快照、--no-prebak 跳过先备份（默认恢复前先备份）
- 多源路径：sh 的 zip 支持密码；bat/ps1 无标准库加密 zip（脚本头有注释说明）
"""

import os
from importlib.resources import files


def _template(flavor: str) -> str:
    return (files("backupapp.scripts") / "templates" / f"script.{flavor}.tpl")\
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


def _tokens(plan, flavor: str) -> dict[str, str]:
    srcs = plan.sources or []
    if flavor == "ps1":
        return {"SRCS_PS": ",\n".join(f"  {_dq(s, 'ps1')}" for s in srcs)}
    if flavor == "sh":
        return {
            "ARCHIVE_ARGS": " ".join(
                f'-C {_dq(os.path.dirname(s), "sh")} {_dq(_base(s), "sh")}'
                for s in srcs),
            # zip 逐源归档，避免绝对路径写入包内目录树
            "ZIP_CMDS": "\n".join(
                f'(cd {_dq(os.path.dirname(s), "sh")} && $ZIP "$OUT" {_dq(_base(s), "sh")})'
                for s in srcs),
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


def generate(app, plan, flavor: str) -> str:
    t = _template(flavor)
    vals = {
        "APP": app.id,
        "PLAN": f"{app.id}/{plan.id}",
        "SRC": plan.sources[0] if plan.sources else "",
        "DEST": plan.destination,
        "FMT": plan.format,
        "COMPRESS": "1" if plan.compress else "0",
        "KEEP": str(plan.retention),
        "MONTHLY": "1" if plan.keep_monthly else "0",
        "YEARLY": "1" if plan.keep_yearly else "0",
        "RETENTION_UNIT": plan.retention_unit or "count",
    }
    vals.update(_tokens(plan, flavor))
    for k, v in vals.items():
        t = t.replace("{{" + k + "}}", v)
    return t


def write_script(path: str, content: str) -> None:
    """ps1 带 UTF-8 BOM（Windows PowerShell 5.1 按 ANSI 读无 BOM 文件会乱码）；
    bat/sh 无 BOM（BOM 会破坏 @echo off / shebang）。"""
    enc = "utf-8-sig" if path.lower().endswith(".ps1") else "utf-8"
    with open(path, "w", encoding=enc, newline="\n") as f:
        f.write(content)
