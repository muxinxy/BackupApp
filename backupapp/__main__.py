"""CLI 入口：全局备份命令、计划任务开关、脚本生成、导入导出、校验。

用法示例：
  backupapp backup --all
  backupapp backup --plan vscode/cfg
  backupapp restore --app vscode [--snapshot 20260808_103000]
  backupapp task on|off|status
  backupapp script --app vscode --plan cfg --flavor ps1
  backupapp export --all -o out.zip
  backupapp import out.zip
  backupapp validate
"""

import argparse
import os
import sys

from . import __version__, scheduler
from .i18n import _
from .storage import importexport, lock, store
from .util import format_size


def _die(msg: str, code: int = 1):
    print(_("error: {msg}").format(msg=msg), file=sys.stderr)
    sys.exit(code)


def cmd_gui(args) -> int:
    from .gui.app import main as gui_main
    return gui_main()


def cmd_backup(args) -> int:
    from .engine import backup as bk
    try:
        if args.all:
            results = bk.run_all()
        elif args.app:
            results = bk.run_app(args.app)
        else:
            results = [bk.run_plan(args.plan)]
    except ValueError as e:
        _die(str(e))
    for r in results:
        status = "OK " if r.ok else "FAIL"
        extra = (_("{files} files, {size}, pruned {pruned}").format(
                     files=r.files, size=format_size(r.bytes), pruned=r.pruned)
                 if r.ok else _(": {error}").format(error=r.error))
        print(f"[{status}] {r.plan_key} -> {r.archive_path or '-'} {extra}")
    return 0 if all(r.ok for r in results) else 1


def cmd_restore(args) -> int:
    from .engine import restore as rs
    r = rs.restore_plan(f"{args.app}/{args.plan_id}", snapshot=args.snapshot)
    print(("OK " if r.ok else "FAIL") + _(" {key} <- {snapshot}").format(
              key=r.plan_key, snapshot=r.snapshot)
          + ("" if r.ok else _(": {error}").format(error=r.error)))
    return 0 if r.ok else 1


def cmd_task(args) -> int:
    cfg = store.load_settings()
    if args.action == "on":
        ok = scheduler.install(cfg)
        print("task installed" if ok else "task install failed")
        return 0 if ok else 1
    if args.action == "off":
        ok = scheduler.uninstall(cfg)
        print("task removed" if ok else "task remove failed")
        return 0 if ok else 1
    st = scheduler.status(cfg)
    print(f"task status: {st}")
    print(f"global command: {scheduler.app_command(cfg)}")
    return 0


def cmd_self_backup(args) -> int:
    from .protocols.runner import run_self_backup
    results = run_self_backup(protocol=args.protocol)
    for r in results:
        if r.ok:
            print(_("OK {name} -> {remote} ({files} 文件, {size}, 清理 {pruned} 个旧备份)").format(
                name=r.remote_name, remote=r.remote, files=r.files,
                size=format_size(r.bytes), pruned=r.pruned))
            if r.local_path:
                print(_("   本地副本: {path}").format(path=r.local_path))
        else:
            print(_("FAIL: {error}").format(error=r.error), file=sys.stderr)
    return 0 if all(r.ok for r in results) else 1


def cmd_self_list(args) -> int:
    from .protocols.runner import list_remote_files
    try:
        files = list_remote_files(args.protocol)
    except Exception as e:
        _die(str(e))
    for f in files:
        size = f"{f.size:,}" if f.size else "-"
        print(f"{f.name}\t{size} B\t{f.mtime}")
    return 0


def cmd_self_restore(args) -> int:
    from .protocols.runner import run_self_restore
    r = run_self_restore(args.protocol, args.file, overwrite=not args.no_overwrite)
    if r.ok:
        print(_("OK 已恢复 {proto}://{name} ({files} 个文件)").format(
            proto=r.protocol, name=r.remote_name, files=r.files))
        return 0
    print(_("FAIL: {error}").format(error=r.error), file=sys.stderr)
    return 1


def cmd_self_delete(args) -> int:
    from .protocols.runner import delete_remote_file
    err = delete_remote_file(args.protocol, args.file)
    if err:
        print(_("FAIL: {error}").format(error=err), file=sys.stderr)
        return 1
    print(_("OK 已删除 {file}").format(file=args.file))
    return 0


def cmd_export(args) -> int:
    if args.app:
        app = store.load_app(args.app)
        if not app:
            _die(_("应用不存在: {app}").format(app=args.app))
        importexport.write_one(app, args.output)
        print(_("已导出 {id} -> {path}").format(id=app.id, path=args.output))
    else:
        ids = importexport.export_all(args.output)
        print(_("已导出 {n} 个应用到 {path}").format(n=len(ids), path=args.output))
    return 0


def cmd_import(args) -> int:
    ids = importexport.import_(args.path)
    print(_("已导入: {ids}").format(ids=", ".join(ids)))
    return 0


def cmd_validate(args) -> int:
    from .engine import paths
    problems = 0
    apps = store.list_apps()
    print(_("{apps} 个应用，{plans} 个计划").format(
        apps=len(apps), plans=sum(len(a.plans) for a in apps)))
    for app in apps:
        for plan in app.plans:
            for s in plan.sources:
                p = paths.expand(s)
                if not os.path.exists(p):
                    print(_("  [warn] {key} 源不存在: {path}").format(
                        key=f"{app.id}/{plan.id}", path=p))
                    problems += 1
            d = paths.expand(plan.destination)
            print(f"  [{'ok' if os.path.isdir(d) else 'warn'}] {app.id}/{plan.id} -> {d}")
            if not os.path.isdir(d):
                problems += 1
    return 0 if problems == 0 else 1


def cmd_script(args) -> int:
    from .scripts import generator
    pair = store.load_plan(args.app, args.plan_id)
    if not pair:
        _die(_("计划不存在: {key}").format(key=f"{args.app}/{args.plan_id}"))
    app, plan = pair
    content = generator.generate(app, plan, args.flavor)
    if args.output:
        generator.write_script(args.output, content)
        print(_("脚本已生成 -> {path}").format(path=args.output))
    else:
        print(content)
    return 0


def cmd_app(args) -> int:
    from .model import AppConfig
    if args.action == "list":
        for app in store.list_apps():
            print(f"{app.id}\t{app.name}\t" + _("{n} 个计划").format(n=len(app.plans)))
        return 0
    if args.action == "new":
        if not args.id or not args.name:
            _die(_("app new 需要 --id 和 --name"))
        app = AppConfig(id=args.id, name=args.name, vendor=args.vendor or "",
                        version=args.version or "", note=args.note or "",
                        config_paths=args.config_path or [],
                        data_paths=args.data_path or [])
        store.save_app(app)
        print(_("app created: {id}（计划请直接编辑 apps/{id}.json，GUI 下一阶段）").format(id=app.id))
        return 0
    if args.action == "rm":
        store.delete_app(args.id)
        print(_("app removed: {id}").format(id=args.id))
        return 0
    _die(_("未知 app 动作: {action}").format(action=args.action))


def _add_app_parser(sub) -> None:
    p = sub.add_parser("app", help=_("应用管理"))
    p.add_argument("action", choices=["list", "new", "rm"])
    p.add_argument("--id")
    p.add_argument("--name")
    p.add_argument("--vendor")
    p.add_argument("--version")
    p.add_argument("--note")
    p.add_argument("--config-path", action="append", default=[])
    p.add_argument("--data-path", action="append", default=[])


def _portable_root() -> str:
    """便携数据根：冻结 exe 用 exe 目录，开发模式用当前目录。"""
    if getattr(sys, "frozen", False):
        return os.path.join(os.path.dirname(sys.executable), "data")
    return os.path.join(os.getcwd(), "data")


def main(argv: list[str] | None = None) -> int:
    # 窗口化（console=False）构建下 stdout/stderr 为 None：重定向到空设备，
    # 保证 CLI 子命令（含计划任务调用）不因 print 崩溃、退出码正确
    if sys.stdout is None:
        sys.stdout = open(os.devnull, "w", encoding="utf-8")
    if sys.stderr is None:
        sys.stderr = open(os.devnull, "w", encoding="utf-8")
    # Windows 控制台默认 cp1252，强制 UTF-8 输出，避免打印中文模板/日志崩溃
    for _s in (sys.stdout, sys.stderr):
        if _s is not None:
            _s.reconfigure(encoding="utf-8", errors="replace")

    # 预扫描 --data-dir（在 argparse 构造前），以便 --help 也能按语言渲染
    _data_dir = None
    for _i, _a in enumerate(sys.argv):
        if _a == "--data-dir" and _i + 1 < len(sys.argv):
            _data_dir = sys.argv[_i + 1]
    store.set_data_root(_data_dir or _portable_root())
    from .i18n import set_language
    set_language(store.load_settings().general.language)

    p = argparse.ArgumentParser(prog="backupapp", description=__doc__)
    p.add_argument("--version", action="version", version=__version__)
    p.add_argument("--data-dir", help=_("数据目录（默认便携：exe/当前目录下 data/）"))
    sub = p.add_subparsers(dest="cmd")

    sub.add_parser("gui", help=_("启动图形界面"))
    p2 = sub.add_parser("backup", help=_("执行备份"))
    p2.add_argument("--all", action="store_true")
    p2.add_argument("--app")
    p2.add_argument("--plan")
    p3 = sub.add_parser("restore", help=_("恢复备份"))
    p3.add_argument("--app", required=True)
    p3.add_argument("--plan-id", required=True)
    p3.add_argument("--snapshot")
    p4 = sub.add_parser("task", help=_("全局计划任务开关"))
    p4.add_argument("action", choices=["on", "off", "status"])
    sub.add_parser("validate", help=_("校验所有应用/计划配置"))
    p5 = sub.add_parser("export", help=_("导出应用配置"))
    p5.add_argument("--app")
    p5.add_argument("--all", action="store_true")
    p5.add_argument("-o", "--output", required=True)
    p6 = sub.add_parser("import", help=_("导入应用配置"))
    p6.add_argument("path")
    p7 = sub.add_parser("script", help=_("生成备份/恢复一体脚本"))
    p7.add_argument("--app", required=True)
    p7.add_argument("--plan-id", required=True)
    p7.add_argument("--flavor", choices=["ps1", "bat", "sh"], default="ps1")
    p7.add_argument("-o", "--output")
    p_sb = sub.add_parser("self-backup", help=_("执行自身备份（默认全部启用的协议）"))
    p_sb.add_argument("--protocol", help=_("只备份指定协议: webdav|s3|ftp|sftp"))
    p_sl = sub.add_parser("self-list", help=_("列出远程自身备份文件"))
    p_sl.add_argument("--protocol", required=True,
                      choices=["webdav", "s3", "ftp", "sftp"])
    p_sr = sub.add_parser("self-restore", help=_("从远程恢复自身备份"))
    p_sr.add_argument("--protocol", required=True,
                      choices=["webdav", "s3", "ftp", "sftp"])
    p_sr.add_argument("--file", required=True, help=_("远程备份文件名"))
    p_sr.add_argument("--no-overwrite", action="store_true",
                      help=_("跳过本机已存在的应用（相同 id 保留现有）"))
    p_sd = sub.add_parser("self-delete", help=_("删除远程自身备份文件"))
    p_sd.add_argument("--protocol", required=True,
                      choices=["webdav", "s3", "ftp", "sftp"])
    p_sd.add_argument("--file", required=True)
    _add_app_parser(sub)

    args = p.parse_args(argv)

    if args.data_dir:
        store.set_data_root(args.data_dir)
    else:
        store.set_data_root(_portable_root())

    from . import logging as applog
    applog.get_logger().info("CLI 启动")

    # 无子命令（如双击 exe）默认启动 GUI
    if not args.cmd:
        return cmd_gui(args)

    handlers = {
        "gui": cmd_gui,
        "backup": cmd_backup,
        "restore": cmd_restore,
        "task": cmd_task,
        "self-backup": cmd_self_backup,
        "self-list": cmd_self_list,
        "self-restore": cmd_self_restore,
        "self-delete": cmd_self_delete,
        "export": cmd_export,
        "import": cmd_import,
        "validate": cmd_validate,
        "script": cmd_script,
        "app": cmd_app,
    }
    return handlers[args.cmd](args)


if __name__ == "__main__":
    sys.exit(main())
