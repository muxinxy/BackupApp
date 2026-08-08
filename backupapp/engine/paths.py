"""路径解析：展开环境变量与 ~；存储时保留变量形式，运行时展开为绝对路径。"""

import os

# 变量替换优先级：最长前缀优先（如 %APPDATA% 先于 %USERPROFILE%）
_VARS = ("APPDATA", "LOCALAPPDATA", "USERPROFILE", "PROGRAMFILES",
         "PROGRAMDATA", "TEMP", "TMP", "HOME", "XDG_CONFIG_HOME",
         "XDG_DATA_HOME")


def expand(p: str) -> str:
    p = os.path.expandvars(os.path.expanduser(str(p).strip()))
    return os.path.abspath(p)


def expand_many(paths: list[str]) -> list[str]:
    return [expand(p) for p in paths]


def compact(p: str) -> str:
    """绝对路径 -> 变量形式（如 %APPDATA%/Code、~/cfg），便于跨机器导入。

    最长前缀优先：%APPDATA% 长于 %USERPROFILE% 时优先语义化变量；
    与 ~ 同长时 ~ 优先。非绝对路径/变量形式原样返回。
    """
    p = os.path.normpath(p)
    if not os.path.isabs(p):
        return p
    lower = p.lower()
    candidates = []  # (前缀长度, 变量名, 变量串)
    for name in _VARS:
        val = os.environ.get(name)
        if not val:
            continue
        val = os.path.normpath(val)
        vlow = val.lower()
        if vlow == lower:
            candidates.append((len(val), name, f"%{name}%"))
        elif lower.startswith(vlow + os.sep):
            candidates.append((len(val), name, f"%{name}%"))

    home = None
    for name in ("USERPROFILE", "HOME"):
        val = os.environ.get(name)
        if val:
            val = os.path.normpath(val)
            if val.lower() == lower:
                return "~"
            if lower.startswith(val.lower() + os.sep):
                home = (len(val), val)
                break

    best = max(candidates, key=lambda c: c[0]) if candidates else None
    if home and (best is None or home[0] >= best[0]):
        return "~" + p[len(home[1]):]
    if best:
        return best[2] + p[best[0]:]
    return p

