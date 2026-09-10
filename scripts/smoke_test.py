"""冒烟测试：压缩格式往返 + 保留策略 + 路径展开。

用法: .venv\Scripts\python scripts\smoke_test.py
"""

import os
import shutil
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from backupapp.engine import compress, retention  # noqa: E402
from backupapp.storage import store  # noqa: E402


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

    # 保留策略：自身备份名带设备名段，排序必须按时间戳而非整个文件名。
    # 两台设备共用一个目录时，按文件名倒序会先比设备名 -> 删掉最新备份。
    dest2 = os.path.join(tmp, "dest_self")
    os.makedirs(dest2)
    self_names = [
        "backupapp_Alpha_20260101_000000.zip",  # Alpha 旧
        "backupapp_Alpha_20260901_000000.zip",  # Alpha 新（最新的一份）
        "backupapp_Zeta_20260102_000000.zip",   # Zeta 旧
        "backupapp_Zeta_20260103_000000.zip",   # Zeta 稍新
    ]
    for n in self_names:
        with open(os.path.join(dest2, n), "w") as f:
            f.write("x")
    removed = retention.prune(dest2, "backupapp", 2, False)
    left_names = sorted(os.path.basename(e) for e in retention.list_entries(dest2, "backupapp"))
    assert left_names == ["backupapp_Alpha_20260901_000000.zip",
                          "backupapp_Zeta_20260103_000000.zip"], \
        f"自身备份保留按设备名排序，删错了最新备份: {left_names}"
    assert removed == 2, f"removed={removed}"
    # snapshot_of 对带设备名的自身备份也要能取到时间戳
    assert retention.snapshot_of(self_names[0]) == "20260101_000000", \
        f"snapshot_of 自身备份名失败: {retention.snapshot_of(self_names[0])}"
    print(f"[ok] retention self-backup by timestamp: {left_names}")

    # 原子写：正常写入后不留临时文件，内容可读回
    data_root = os.path.join(tmp, "data_root")
    os.makedirs(data_root)
    store.set_data_root(data_root)
    app = store.AppConfig(id="atomic", name="Atomic")
    store.save_app(app)
    got = store.load_app("atomic")
    assert got and got.name == "Atomic", f"原子写往返失败: {got}"
    stray = [n for n in os.listdir(store.apps_dir()) if n.startswith(".tmp_")]
    assert not stray, f"原子写残留临时文件: {stray}"
    print("[ok] atomic json write")

    # 损坏 JSON 视为无数据（记日志），不抛异常、不阻断启动
    with open(store.settings_path(), "w", encoding="utf-8") as f:
        f.write('{"general": {"language": "en"')  # 半截 JSON
    assert store.load_settings() is not None, "损坏 settings.json 应回退默认值"
    print("[ok] corrupt json falls back to defaults")

    # 写失败不能破坏已存在的文件（临时文件 + os.replace 的意义）
    store.save_app(app)
    good = open(store.app_path("atomic"), "rb").read()

    class _Boom(store.AppConfig):
        pass

    bad = store.AppConfig(id="atomic", name="Atomic")
    bad.to_dict = lambda: (_ for _ in ()).throw(RuntimeError("boom"))
    try:
        store.save_app(bad)
    except RuntimeError:
        pass
    assert open(store.app_path("atomic"), "rb").read() == good, \
        "写失败后原文件被破坏"
    stray = [n for n in os.listdir(store.apps_dir()) if n.startswith(".tmp_")]
    assert not stray, f"写失败后残留临时文件: {stray}"
    print("[ok] failed write leaves original intact")

    # 压缩失败：不留下以最终名（匹配 ENTRY_RE/SNAP_RE）落盘的半截文件
    bad_dest = os.path.join(tmp, "part_dest")
    os.makedirs(bad_dest)
    entry = retention.entry_path(bad_dest, "app2", "20260601_000000", True, "zip")
    try:
        compress.create_archive([os.path.join(tmp, "no_such_dir")], entry,
                                "bogusfmt", "", [])
    except ValueError:
        pass
    else:
        raise AssertionError("不支持的格式应抛 ValueError")
    assert not os.path.exists(entry), f"失败后留下了最终名文件: {entry}"
    stray = [n for n in os.listdir(bad_dest) if n.endswith(".part")]
    assert not stray, f"失败后残留 .part 文件: {stray}"
    # 正常路径：成功后 .part 改名成最终名，且目录里没有 .part 残留
    compress.create_archive([src], entry, "zip", "", [])
    assert os.path.isfile(entry), "成功路径应产出最终归档"
    assert not [n for n in os.listdir(bad_dest) if n.endswith(".part")], \
        "成功路径不应残留 .part"
    print("[ok] partial archive not left at final name")

    # DataLock：同线程可重入（GUI worker 持锁后引擎入口再取不应失败）
    from backupapp.storage import lock as dlock
    lp = os.path.join(tmp, "test.lock")
    with dlock.DataLock(lp):
        with dlock.DataLock(lp):
            with dlock.DataLock(lp):
                pass
    # 退出最外层后锁应真正释放：另一个线程能立即拿到
    released = []
    import threading as _th

    def _grab():
        try:
            with dlock.DataLock(lp):
                released.append("acquired")
        except RuntimeError as e:
            released.append(f"blocked: {e}")

    with dlock.DataLock(lp):
        t = _th.Thread(target=_grab)
        t.start()
        t.join()
        assert released and released[0].startswith("blocked"), \
            f"持锁期间其他线程不应拿到锁: {released}"
    released.clear()
    t = _th.Thread(target=_grab)
    t.start()
    t.join()
    assert released == ["acquired"], f"锁未在退出后释放: {released}"
    print("[ok] datalock reentrant + released")

    # 路径穿越防护：带 ../ 的 tar.gz 成员必须被拒绝，不能写到目标目录之外
    import io as _io
    import tarfile as _tarfile
    evil = os.path.join(tmp, "evil.tar.gz")
    with _tarfile.open(evil, "w:gz") as t:
        data = b"pwned"
        info = _tarfile.TarInfo("../escaped.txt")
        info.size = len(data)
        t.addfile(info, _io.BytesIO(data))
    outdir = os.path.join(tmp, "evil_out")
    escaped = os.path.join(tmp, "escaped.txt")
    try:
        compress.extract_archive(evil, outdir, "")
    except ValueError as e:
        assert "越界" in str(e) or "非法" in str(e), f"错误类型不对: {e}"
    else:
        raise AssertionError("带 ../ 的归档应被拒绝")
    assert not os.path.exists(escaped), "路径穿越写到了目标目录外"
    print("[ok] tar.gz path traversal rejected")

    # 同一防护的旧版本回退路径：直接调 _check_member 校验成员名逻辑
    for bad in ("../evil", "..\\evil", "/abs/evil", "C:/evil"):
        try:
            compress._check_member(bad, outdir, "tar.gz")
        except ValueError:
            pass
        else:
            raise AssertionError(f"应拒绝越界成员: {bad}")
    compress._check_member("data/apps/x.json", outdir, "tar.gz")  # 正常成员放行
    print("[ok] member name validation")

    # is_link：真实目录（哪怕其父目录是链接）不能被判成链接，否则 link 模式
    # 会跳过搬迁建链、甚至删掉真实目录。这里用一个 junction/symlink 父目录验证。
    from backupapp.engine import link as linkmod
    import subprocess as _sp
    real_parent = os.path.join(tmp, "real_parent")
    os.makedirs(real_parent)
    child = os.path.join(real_parent, "child")
    os.makedirs(child)
    assert not linkmod.is_link(child), "普通目录不应被判为链接"
    # 建一个链接指向真实目录，被指向的目录本身也不能被判成链接
    link_path = os.path.join(tmp, "link_to_parent")
    made_link = False
    if os.name == "nt":
        # 中文系统 mklink 输出为 GBK，用 bytes + 容错解码避免 reader 线程崩
        r = _sp.run(["cmd", "/c", "mklink", "/J", link_path, real_parent],
                    capture_output=True)
        made_link = r.returncode == 0
    else:
        try:
            os.symlink(real_parent, link_path)
            made_link = True
        except OSError:
            made_link = False
    if made_link:
        assert linkmod.is_link(link_path), "链接本身应被判为链接"
        assert not linkmod.is_link(child), \
            "链接指向的真实子目录不应被判为链接（父目录是链接也不行）"
        # remove_link 只能删链接本身，真实目录必须保留
        linkmod.remove_link(link_path)
        assert not os.path.exists(link_path), "链接未被删除"
        assert os.path.isdir(child), "remove_link 误删了真实目录"
        print("[ok] is_link distinguishes links from real dirs")
    else:
        print("[ok] is_link real-dir check (link creation unavailable, skipped)")

    # create_link 失败时必须给出真实错误信息：mklink 输出是 GBK，若按默认
    # UTF-8 解码会静默清空输出（PYTHONUTF8=1 环境下 reader 线程解码失败）。
    if os.name == "nt":
        existing = os.path.join(tmp, "already_exists")
        os.makedirs(existing)
        try:
            linkmod.create_link(existing, real_parent, "junction")
        except RuntimeError as e:
            msg = str(e)
            assert msg.strip() != "创建链接失败:" and len(msg) > len("创建链接失败: "), \
                f"链接失败时错误详情丢失: {msg!r}"
            print(f"[ok] create_link surfaces real error: {msg[:40]}")
        else:
            raise AssertionError("目标已存在时 create_link 应失败")

    # 自我包含防护：目标目录在源目录内时，归档不能把历史备份再打进去。
    # 这里跑两次备份，第二次的体积不应因第一次的产物而显著膨胀。
    from backupapp.engine import backup as _backup
    from backupapp.model import AppConfig as _App, BackupPlan as _Plan
    inc_root = os.path.join(tmp, "include_root")
    os.makedirs(inc_root)
    with open(os.path.join(inc_root, "data.txt"), "w") as f:
        f.write("payload")
    inc_dest = os.path.join(inc_root, "backups")  # 目标在源内部
    pair = _App(id="inc", name="Inc",
                plans=[_Plan(id="p", name="p", sources=[inc_root],
                             destination=inc_dest, compress=True, format="zip")])
    store.save_app(pair)
    r1 = _backup.run_plan("inc/p")
    assert r1.ok, r1.error
    r2 = _backup.run_plan("inc/p")
    assert r2.ok, r2.error
    # 第二次若把第一份归档也打进去，体积会明显变大（至少翻倍）
    assert r2.bytes < r1.bytes * 2, \
        f"备份自我包含：第二份 {r2.bytes}B 相对第一份 {r1.bytes}B 明显膨胀"
    # 归档内不含 backups/ 路径
    names = _names(r2.archive_path)
    assert not any("backups/" in n for n in names), \
        f"归档包含了目标目录内容: {names}"
    print(f"[ok] self-inclusion guard ({r1.bytes}B -> {r2.bytes}B)")

    # 恢复失败要回滚：源目录内容不能被半成品替换，且不留临时解压目录
    from backupapp.engine import restore as _restore
    rs_root = os.path.join(tmp, "rs_root")
    os.makedirs(rs_root)
    with open(os.path.join(rs_root, "important.txt"), "w") as f:
        f.write("precious")
    rs_dest = os.path.join(tmp, "rs_dest")
    os.makedirs(rs_dest)
    # 造一个损坏的归档，让解压必然失败
    bad_entry = retention.entry_path(rs_dest, "rsapp", "20260101_000000", True, "zip")
    with open(bad_entry, "w") as f:
        f.write("this is not a zip")
    rpair = _App(id="rsapp", name="RS",
                 plans=[_Plan(id="p", name="p", sources=[rs_root],
                              destination=rs_dest, compress=True, format="zip")])
    store.save_app(rpair)
    before = os.listdir(tmp)
    rr = _restore.restore_plan("rsapp/p")
    assert not rr.ok, "损坏归档的恢复应当失败"
    # 源目录必须还原（回滚成功），而不是留下空目录或残缺内容
    assert os.path.isdir(rs_root) and os.path.isfile(
        os.path.join(rs_root, "important.txt")), "恢复失败后源目录未回滚"
    with open(os.path.join(rs_root, "important.txt")) as f:
        assert f.read() == "precious", "回滚后内容不一致"
    leaked = [n for n in os.listdir(tmp)
              if n not in before and n.startswith("backupapp_restore_")]
    assert not leaked, f"失败路径残留临时目录: {leaked}"
    print("[ok] failed restore rolls back and cleans temp dir")

    # 目标目录位于源目录内时的恢复：必须先解压再改名 source，否则归档会跟着
    # 源目录一起被搬走，解压时报"文件不存在"（dist 验证时实测到的问题）。
    inc_src = os.path.join(tmp, "inrestore_src")
    os.makedirs(inc_src)
    with open(os.path.join(inc_src, "keep.txt"), "w") as f:
        f.write("original")
    inc_dest2 = os.path.join(inc_src, "bk")  # 目的在源内部
    pair2 = _App(id="inrestore", name="IR",
                 plans=[_Plan(id="p", name="p", sources=[inc_src],
                              destination=inc_dest2, compress=True, format="zip")])
    store.save_app(pair2)
    rb = _backup.run_plan("inrestore/p")
    assert rb.ok, rb.error
    # 改坏源内容后恢复
    with open(os.path.join(inc_src, "keep.txt"), "w") as f:
        f.write("corrupted")
    rr2 = _restore.restore_plan("inrestore/p")
    assert rr2.ok, f"目的在源内的恢复失败: {rr2.error}"
    with open(os.path.join(inc_src, "keep.txt")) as f:
        assert f.read() == "original", "恢复后内容未还原"
    print("[ok] restore with destination inside source")

    # 同一秒内重复备份不能互相覆盖（快照名精确到秒）
    uni_dest = os.path.join(tmp, "uni_dest")
    os.makedirs(uni_dest)
    snap = "20260601_120000"
    first = retention.unique_snapshot(uni_dest, "uapp", snap)
    assert first == snap, f"无冲突时应保持原名: {first}"
    with open(retention.entry_path(uni_dest, "uapp", first, True, "zip"), "w") as f:
        f.write("x")
    second = retention.unique_snapshot(uni_dest, "uapp", snap)
    assert second != first, "同名快照应被避让"
    assert second == "20260601_120001", f"应逐秒前移: {second}"
    print(f"[ok] unique snapshot avoids overwrite: {first} -> {second}")

    # 计划任务命令比对：schtasks 会吞掉 /tr 的前导引号（实测回读为
    # 'exe" backup --all"'），逐字比较会误报 pathMismatch，界面就一直是
    # "路径变更，需重新应用"。
    from backupapp import scheduler as _sched
    expected = '"C:\\App\\backupapp.exe" backup --all'
    # schtasks 实际回读形态：丢了前导引号、尾引号还在
    as_stored = 'C:\\App\\backupapp.exe" backup --all"'
    assert _sched._cmd_matches(expected, as_stored), \
        f"引号差异不应判为路径变更: {as_stored!r}"
    # 正常无引号形式
    assert _sched._cmd_matches(expected, "C:\\App\\backupapp.exe backup --all")
    # 额外空白/多空格也应通过
    assert _sched._cmd_matches(expected, 'C:\\App\\backupapp.exe   backup    --all')
    # 真的换了路径必须仍能识别出来
    assert not _sched._cmd_matches(expected, 'D:\\Other\\backupapp.exe backup --all')
    # 空命令不应算匹配（避免"查不到命令"被误判成已注册正确）
    assert not _sched._cmd_matches(expected, "")
    print("[ok] scheduler command matching tolerates quote loss")

    # .old 安全网目录按份数清理（只留最近 3 份）
    for i in range(6):
        os.makedirs(os.path.join(tmp, f"rs_root.2026010{i}_000000.old"))
    _restore._prune_old_siblings(rs_root, keep=3)
    left_old = sorted(n for n in os.listdir(tmp)
                      if n.startswith("rs_root.") and n.endswith(".old"))
    assert len(left_old) == 3, f".old 清理后应剩 3 份: {left_old}"
    assert left_old == sorted(left_old)[-3:] or left_old[-1].endswith("000000.old")
    print(f"[ok] .old safety dirs pruned to {len(left_old)}")

    # 钩子：非零退出码报错、超时被杀、成功时无异常
    from backupapp.engine import hooks as _hooks
    fail_cmd = "exit 3" if os.name == "nt" else "exit 3"
    try:
        _hooks.run_hook(fail_cmd, 30, "hooktest", "备份前")
    except RuntimeError as e:
        assert "3" in str(e), f"退出码未出现在错误里: {e}"
    else:
        raise AssertionError("非零退出码应抛 RuntimeError")
    # 超时：命令睡眠远超 timeout，必须抛超时错误且不能挂住
    import time as _time
    slow = "ping -n 30 127.0.0.1 >nul" if os.name == "nt" else "sleep 30"
    t0 = _time.time()
    try:
        _hooks.run_hook(slow, 1, "hooktest", "备份后")
    except RuntimeError as e:
        assert "超时" in str(e), f"应为超时错误: {e}"
    else:
        raise AssertionError("超时应抛 RuntimeError")
    elapsed = _time.time() - t0
    assert elapsed < 20, f"超时未及时返回，耗时 {elapsed:.1f}s"
    print(f"[ok] hooks: nonzero exit + timeout killed ({elapsed:.1f}s)")
    # 成功路径不应抛异常，且能读到输出
    ok_cmd = "echo hooked" if os.name == "nt" else "echo hooked"
    _hooks.run_hook(ok_cmd, 30, "hooktest", "备份前")
    print("[ok] hook success path")

    shutil.rmtree(tmp, ignore_errors=True)
    print("ALL PASS")


def _names(arc: str) -> list[str]:
    import pyzipper
    with pyzipper.ZipFile(arc) as z:
        return z.namelist()


if __name__ == "__main__":
    main()
