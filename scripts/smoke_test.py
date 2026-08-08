"""冒烟测试：压缩格式往返 + 保留策略 + 路径展开。

用法: .venv\Scripts\python scripts\smoke_test.py
"""

import os
import shutil
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from backupapp.engine import compress, retention  # noqa: E402


def main() -> None:
    tmp = tempfile.mkdtemp(prefix="backupapp_fmt_")
    src = os.path.join(tmp, "config")
    os.makedirs(os.path.join(src, "sub"))
    with open(os.path.join(src, "a.txt"), "w") as f:
        f.write("aaa")
    with open(os.path.join(src, "sub", "b.txt"), "w") as f:
        f.write("bbb")

    # 三格式创建+提取往返
    for fmt in ("zip", "7z", "tar.gz"):
        pw = "pw" if fmt != "tar.gz" else ""
        arc = os.path.join(tmp, f"t.{fmt}")
        compress.create_archive([src], arc, fmt, pw, [])
        out = os.path.join(tmp, fmt)
        compress.extract_archive(arc, out, pw)
        got = set()
        for root, _, files in os.walk(os.path.join(out, "config")):
            for f in files:
                got.add(os.path.relpath(os.path.join(root, f), os.path.join(out, "config")))
        assert got == {"a.txt", os.path.join("sub", "b.txt")}, f"{fmt}: {got}"
        print(f"[ok] {fmt} roundtrip")

    # exclude 生效
    arc = os.path.join(tmp, "t2.zip")
    compress.create_archive([src], arc, "zip", "", ["sub"])
    assert "config/sub/b.txt" not in _names(arc), "exclude 未生效"
    print("[ok] exclude")

    # 保留策略：keep=2 + keepMonthly
    dest = os.path.join(tmp, "dest")
    os.makedirs(dest)
    for snap in ("20260101_000000", "20260115_000000", "20260201_000000",
                 "20260210_000000", "20260305_000000"):
        with open(retention.entry_path(dest, "app", snap, False), "w") as f:
            f.write("x")
    removed = retention.prune(dest, "app", 2, True)
    left = sorted(retention.snapshot_of(e) for e in retention.list_entries(dest, "app"))
    # 最近 2 份（0305、0210）；未覆盖月份各留最新一份（0115 代表 1 月）
    assert left == ["20260115_000000", "20260210_000000", "20260305_000000"], \
        f"retention: {left}"
    assert removed == 2, f"removed={removed}"
    print(f"[ok] retention keep=2+monthly: {left}")

    shutil.rmtree(tmp, ignore_errors=True)
    print("ALL PASS")


def _names(arc: str) -> list[str]:
    import pyzipper
    with pyzipper.ZipFile(arc) as z:
        return z.namelist()


if __name__ == "__main__":
    main()
