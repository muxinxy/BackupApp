"""压缩格式注册表：zip(AES) / 7z / tar.gz，以及非压缩目录拷贝。"""

import fnmatch
import os
import shutil


def _excluded(rel: str, excludes: list[str]) -> bool:
    for pat in excludes:
        if fnmatch.fnmatch(rel, pat) or fnmatch.fnmatch(os.path.basename(rel), pat):
            return True
        if any(fnmatch.fnmatch(part, pat) for part in rel.split(os.sep)):
            return True
    return False


def _iter_files(src_dirs: list[str], excludes: list[str]):
    """产出 (完整路径, 归档内路径)。归档内每个源目录以其 basename 为根。"""
    for src in src_dirs:
        base = os.path.basename(src.rstrip("/\\"))
        if os.path.isdir(src):
            for root, dirs, files in os.walk(src):
                rel = os.path.relpath(root, src)
                dirs[:] = [d for d in dirs if not _excluded(
                    d if rel == "." else os.path.join(rel, d), excludes)]
                for f in files:
                    full = os.path.join(root, f)
                    r = f if rel == "." else os.path.join(rel, f)
                    if _excluded(r, excludes):
                        continue
                    yield full, os.path.join(base, r)
        else:
            yield src, os.path.join(base, os.path.basename(src))


def _count(files: list[tuple[str, str]]) -> tuple[int, int]:
    n, total = 0, 0
    for full, _ in files:
        n += 1
        try:
            total += os.path.getsize(full)
        except OSError:
            pass
    return n, total


def create_archive(src_dirs: list[str], archive_path: str, fmt: str,
                   password: str, excludes: list[str]) -> tuple[int, int]:
    """压缩 src_dirs 到 archive_path，返回 (文件数, 字节数)。"""
    items = list(_iter_files(src_dirs, excludes))
    if fmt == "zip":
        import pyzipper
        if password:
            with pyzipper.AESZipFile(archive_path, "w",
                                     compression=pyzipper.ZIP_DEFLATED) as z:
                z.setpassword(password.encode("utf-8"))
                z.setencryption(pyzipper.WZ_AES)
                for full, arc in items:
                    z.write(full, arc)
        else:
            with pyzipper.ZipFile(archive_path, "w",
                                  compression=pyzipper.ZIP_DEFLATED) as z:
                for full, arc in items:
                    z.write(full, arc)
    elif fmt == "7z":
        import py7zr
        with py7zr.SevenZipFile(archive_path, "w",
                                password=password or None) as z:
            for full, arc in items:
                z.write(full, arc)
    elif fmt == "tar.gz":
        import tarfile
        with tarfile.open(archive_path, "w:gz") as t:
            for full, arc in items:
                t.add(full, arcname=arc)
    else:
        raise ValueError(f"不支持的压缩格式: {fmt}")
    return _count(items)


def extract_archive(archive_path: str, dest_dir: str, password: str) -> None:
    os.makedirs(dest_dir, exist_ok=True)
    if archive_path.endswith(".zip"):
        import pyzipper
        if password:
            with pyzipper.AESZipFile(archive_path, "r") as z:
                z.setpassword(password.encode("utf-8"))
                z.extractall(dest_dir)
        else:
            with pyzipper.ZipFile(archive_path, "r") as z:
                z.extractall(dest_dir)
    elif archive_path.endswith(".7z"):
        import py7zr
        with py7zr.SevenZipFile(archive_path, "r", password=password or None) as z:
            z.extractall(dest_dir)
    elif archive_path.endswith(".tar.gz"):
        import tarfile
        with tarfile.open(archive_path, "r:gz") as t:
            t.extractall(dest_dir)
    else:
        raise ValueError(f"不支持的压缩格式: {archive_path}")


def copy_tree(src_dirs: list[str], entry: str, excludes: list[str]) -> tuple[int, int]:
    """非压缩备份：拷贝为目录树 entry/。返回 (文件数, 字节数)。"""
    os.makedirs(entry, exist_ok=True)
    n, total = 0, 0
    for full, arc in _iter_files(src_dirs, excludes):
        dst = os.path.join(entry, arc)
        os.makedirs(os.path.dirname(dst), exist_ok=True)
        shutil.copy2(full, dst)
        n += 1
        try:
            total += os.path.getsize(full)
        except OSError:
            pass
    return n, total
