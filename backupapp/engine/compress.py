"""压缩格式注册表：zip(AES) / 7z / tar.gz，以及非压缩目录拷贝。"""

import fnmatch
import os
import shutil

from ..i18n import _


def _excluded(rel: str, excludes: list[str]) -> bool:
    for pat in excludes:
        if fnmatch.fnmatch(rel, pat) or fnmatch.fnmatch(os.path.basename(rel), pat):
            return True
        if any(fnmatch.fnmatch(part, pat) for part in rel.split(os.sep)):
            return True
    return False


def normalize_skip_paths(paths) -> tuple[str, ...]:
    """把要跳过的路径规范成可比较形式（绝对路径 + 大小写归一）。"""
    out = []
    for p in paths or ():
        if p:
            out.append(os.path.normcase(os.path.abspath(p)))
    return tuple(out)


def _is_skipped(path: str, skip: tuple[str, ...]) -> bool:
    if not skip:
        return False
    p = os.path.normcase(os.path.abspath(path))
    for s in skip:
        if p == s or p.startswith(s + os.sep):
            return True
    return False


def is_within(path: str, parent: str) -> bool:
    """path 是否是 parent 本身或其子路径（含相等）。"""
    try:
        a = os.path.realpath(path)
        b = os.path.realpath(parent)
        return os.path.commonpath([a, b]) == b
    except ValueError:  # 不同盘符（Windows）
        return False


def _iter_files(src_dirs: list[str], excludes: list[str],
                skip: tuple[str, ...] = ()):
    """产出 (完整路径, 归档内路径)。归档内每个源目录以其 basename 为根。

    skip 中的路径（及其子树）会被跳过：用于排除正在写入的归档本身，
    避免"目标目录在源目录内"时归档被自己读入导致体积无限增长。
    """
    for src in src_dirs:
        base = os.path.basename(src.rstrip("/\\"))
        if os.path.isdir(src):
            for root, dirs, files in os.walk(src):
                rel = os.path.relpath(root, src)
                dirs[:] = [d for d in dirs
                           if not _excluded(
                               d if rel == "." else os.path.join(rel, d), excludes)
                           and not _is_skipped(os.path.join(root, d), skip)]
                for f in files:
                    full = os.path.join(root, f)
                    if _is_skipped(full, skip):
                        continue
                    r = f if rel == "." else os.path.join(rel, f)
                    if _excluded(r, excludes):
                        continue
                    yield full, os.path.join(base, r)
        else:
            if _is_skipped(src, skip):
                continue
            yield src, os.path.join(base, os.path.basename(src))


def _count(files: list[tuple[str, str]]) -> tuple[int, int]:
    n, total = 0, 0
    for full, _arc in files:
        n += 1
        try:
            total += os.path.getsize(full)
        except OSError:
            pass
    return n, total


def create_archive(src_dirs: list[str], archive_path: str, fmt: str,
                   password: str, excludes: list[str],
                   progress=None, skip_paths=()) -> tuple[int, int]:
    """压缩 src_dirs 到 archive_path，返回 (文件数, 字节数)。

    progress(arc, i, total) 每写一个文件回调一次（可选）。
    先写 archive_path + ".part"，成功后再原子改名：中途失败留下的半截文件
    不会以最终名（匹配 ENTRY_RE/SNAP_RE）落盘，避免被当成有效备份参与保留
    计算或出现在恢复列表里。
    skip_paths 中的路径不参与打包（见 _iter_files）。
    """
    part = archive_path + ".part"
    skip = normalize_skip_paths(skip_paths)
    items = list(_iter_files(src_dirs, excludes, skip))
    total = len(items)
    try:
        if fmt == "zip":
            import pyzipper
            if password:
                with pyzipper.AESZipFile(part, "w",
                                         compression=pyzipper.ZIP_DEFLATED) as z:
                    z.setpassword(password.encode("utf-8"))
                    z.setencryption(pyzipper.WZ_AES)
                    for i, (full, arc) in enumerate(items, 1):
                        z.write(full, arc)
                        if progress:
                            progress(arc, i, total)
            else:
                with pyzipper.ZipFile(part, "w",
                                      compression=pyzipper.ZIP_DEFLATED) as z:
                    for i, (full, arc) in enumerate(items, 1):
                        z.write(full, arc)
                        if progress:
                            progress(arc, i, total)
        elif fmt == "7z":
            import py7zr
            with py7zr.SevenZipFile(part, "w",
                                    password=password or None) as z:
                for i, (full, arc) in enumerate(items, 1):
                    z.write(full, arc)
                    if progress:
                        progress(arc, i, total)
        elif fmt == "tar.gz":
            import tarfile
            with tarfile.open(part, "w:gz") as t:
                for i, (full, arc) in enumerate(items, 1):
                    t.add(full, arcname=arc)
                    if progress:
                        progress(arc, i, total)
        else:
            raise ValueError(_("不支持的压缩格式: {fmt}").format(fmt=fmt))
        os.replace(part, archive_path)
    except BaseException:
        try:
            os.unlink(part)
        except OSError:
            pass
        raise
    return _count(items)


def _check_member(name: str, dest_dir: str, fmt: str) -> None:
    """拒绝逃逸出 dest_dir 的归档成员（绝对路径 / .. 穿越 / 盘符路径）。"""
    if not name:
        return
    norm = os.path.normpath(name.replace("\\", "/"))
    if os.path.isabs(norm) or norm.split("/", 1)[0].endswith(":"):
        raise ValueError(
            _("归档包含非法路径，已拒绝解压: {name}").format(name=name))
    target = os.path.realpath(os.path.join(dest_dir, norm))
    root = os.path.realpath(dest_dir)
    if target != root and not target.startswith(root + os.sep):
        raise ValueError(
            _("归档包含越界路径，已拒绝解压: {name}").format(name=name))


def _extract_tar(archive_path: str, dest_dir: str) -> None:
    import tarfile
    with tarfile.open(archive_path, "r:gz") as t:
        try:
            # py3.11.4+/3.12：data 过滤器会剔除绝对路径、..、设备文件与危险链接
            t.extractall(dest_dir, filter="data")
        except TypeError:  # 老版本无 filter 参数：自行校验成员名后解压
            for m in t.getmembers():
                _check_member(m.name, dest_dir, "tar.gz")
            t.extractall(dest_dir)
        except tarfile.FilterError as e:
            # 统一成 ValueError，便于调用方按"归档不可信"处理并显示可翻译文案
            name = getattr(getattr(e, "tarinfo", None), "name", "?")
            raise ValueError(
                _("归档包含越界路径，已拒绝解压: {name}").format(name=name)
            ) from e


def extract_archive(archive_path: str, dest_dir: str, password: str) -> None:
    """解压归档到 dest_dir。

    自身备份会从远程下载归档再解压，因此必须防止归档内的路径穿越
    （绝对路径 / .. / 越界符号链接）写到目标目录之外。
    """
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
            # py7zr 各版本对成员名的处理不一致，解压前统一校验
            for name in z.getnames():
                _check_member(name, dest_dir, "7z")
            z.extractall(dest_dir)
    elif archive_path.endswith(".tar.gz"):
        _extract_tar(archive_path, dest_dir)
    else:
        raise ValueError(
            _("不支持的压缩格式: {archive_path}").format(archive_path=archive_path))


def copy_tree(src_dirs: list[str], entry: str, excludes: list[str],
              progress=None, skip_paths=()) -> tuple[int, int]:
    """非压缩备份：拷贝为目录树 entry/。返回 (文件数, 字节数)。

    progress(arc, i, total) 每拷贝一个文件回调一次（可选）。
    同 create_archive：先拷到 entry + ".part"，成功后再改名为 entry。
    """
    part = entry + ".part"
    skip = normalize_skip_paths(skip_paths)
    items = list(_iter_files(src_dirs, excludes, skip))
    total = len(items)
    n, total_bytes = 0, 0
    try:
        os.makedirs(part, exist_ok=True)
        for i, (full, arc) in enumerate(items, 1):
            dst = os.path.join(part, arc)
            os.makedirs(os.path.dirname(dst), exist_ok=True)
            shutil.copy2(full, dst)
            n += 1
            try:
                total_bytes += os.path.getsize(full)
            except OSError:
                pass
            if progress:
                progress(arc, i, total)
        if os.path.exists(entry):
            shutil.rmtree(entry, ignore_errors=True)
        os.replace(part, entry)
    except BaseException:
        shutil.rmtree(part, ignore_errors=True)
        raise
    return n, total_bytes
