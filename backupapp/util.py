"""通用工具函数。"""


def format_size(n: int) -> str:
    """字节数 -> 人类可读（B / KB / MB / GB / TB）。"""
    if n < 0:
        n = 0
    for unit in ("B", "KB", "MB", "GB"):
        if n < 1024:
            return f"{n:.0f} {unit}" if unit == "B" else f"{n:.1f} {unit}"
        n /= 1024
    return f"{n:.1f} TB"