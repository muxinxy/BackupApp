"""轻量 i18n：gettext 风格 _() + 语言切换 + OS 区域自动检测。零依赖。"""
import locale
import os

_CATALOG: dict[str, str] = {}
_LANG = "zh-CN"


def _detect() -> str:
    """按 OS 区域解析语言：zh* -> zh-CN，其余 -> en。永不抛异常。"""
    candidates = []
    try:
        candidates.append(locale.getlocale()[0])
    except Exception:
        pass
    try:
        candidates.append(locale.getdefaultlocale()[0])
    except Exception:
        pass
    for k in ("LC_ALL", "LANG"):
        try:
            candidates.append(os.environ.get(k))
        except Exception:
            pass
    for c in candidates:
        if c and str(c).lower().startswith("zh"):
            return "zh-CN"
    return "en"


def set_language(lang: str) -> None:
    """设置当前语言。'auto' 按 OS 区域解析；en 加载英文目录；其余回退中文源串。"""
    global _CATALOG, _LANG
    resolved = _detect() if lang == "auto" else lang
    if resolved == "en":
        from .locales import en  # 函数内导入，避免循环依赖
        _CATALOG = en.MESSAGES
    else:
        _CATALOG = {}
    _LANG = resolved


def _(text: str) -> str:
    """翻译：命中目录返回译文，否则返回源串（中文）。"""
    return _CATALOG.get(text, text)


def current_language() -> str:
    return _LANG
