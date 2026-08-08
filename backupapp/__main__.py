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
from .storage import importexport, lock, store


def _die(msg: str, code: int = 1):
    print(f"error: {msg}", file=sys.stderr)
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
        extra = f"{r.files} files, {r.bytes} bytes, pruned {r.pruned}" if r.ok else f": {r.error}"
        print(f"[{status}] {r.plan_key} -> {r.archive_path or '-'} {extra}")
    return 0 if all(r.ok for r in results) else 1


def cmd_restore(args) -> int:
    from .engine import restore as rs
    r = rs.restore_plan(f"{args.app}/{args.plan_id}", snapshot=args.snapshot)
    print(("OK " if r.ok else "FAIL") + f" {r.plan_key} <- {r.snapshot}"
          + ("" if r.ok else f": {r.error}"))
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
    r = run_self_backup()
    if r.ok:
        print(f"OK {r.remote_name} -> {r.remote} ({r.files} 文件, {r.bytes} 字节, "
              f"清理 {r.pruned} 个旧备份)")
        if r.local_path:
            print(f"   本地副本: {r.local_path}")
        return 0
    print(f"FAIL: {r.error}", file=sys.stderr)
    return 1


def cmd_export(args) -> int:
    if args.app:
        app = store.load_app(args.app)
        if not app:
            _die(f"应用不存在: {args.app}")
        importexport.write_one(app, args.output)
        print(f"exported {app.id} -> {args.output}")
    else:
        ids = importexport.export_all(args.output)
        print(f"exported {len(ids)} apps -> {args.output}")
    return 0


def cmd_import(args) -> int:
    ids = importexport.import_(args.path)
    print(f"imported: {', '.join(ids)}")
    return 0


def cmd_validate(args) -> int:
    from .engine import paths
    problems = 0
    apps = store.list_apps()
    print(f"{len(apps)} apps, {sum(len(a.plans) for a in apps)} plans")
    for app in apps:
        for plan in app.plans:
            for s in plan.sources:
                p = paths.expand(s)
                if not os.path.exists(p):
                    print(f"  [warn] {app.id}/{plan.id} 源不存在: {p}")
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
        _die(f"计划不存在: {args.app}/{args.plan_id}")
    app, plan = pair
    content = generator.generate(app, plan, args.flavor)
    if args.output:
        generator.write_script(args.output, content)
        print(f"script -> {args.output}")
    else:
        print(content)
    return 0


def cmd_app(args) -> int:
    from .model import AppConfig
    if args.action == "list":
        for app in store.list_apps():
            print(f"{app.id}\t{app.name}\t{len(app.plans)} plans")
        return 0
    if args.action == "new":
        if not args.id or not args.name:
            _die("app new 需要 --id 和 --name")
        app = AppConfig(id=args.id, name=args.name, vendor=args.vendor or "",
                        version=args.version or "", note=args.note or "",
                        config_paths=args.config_path or [],
                        data_paths=args.data_path or [])
        store.save_app(app)
        print(f"app created: {app.id}（计划请直接编辑 apps/{app.id}.json，GUI 下一阶段）")
        return 0
    if args.action == "rm":
        store.delete_app(args.id)
        print(f"app removed: {args.id}")
        return 0
    _die(f"未知 app 动作: {args.action}")


def _add_app_parser(sub) -> None:
    p = sub.add_parser("app", help="应用管理")
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

    p = argparse.ArgumentParser(prog="backupapp", description=__doc__)
    p.add_argument("--version", action="version", version=__version__)
    p.add_argument("--data-dir", help="数据目录（默认便携：exe/当前目录下 data/）")
    sub = p.add_subparsers(dest="cmd")

    sub.add_parser("gui", help="启动图形界面")
    p2 = sub.add_parser("backup", help="执行备份")
    p2.add_argument("--all", action="store_true")
    p2.add_argument("--app")
    p2.add_argument("--plan")
    p3 = sub.add_parser("restore", help="恢复备份")
    p3.add_argument("--app", required=True)
    p3.add_argument("--plan-id", required=True)
    p3.add_argument("--snapshot")
    p4 = sub.add_parser("task", help="全局计划任务开关")
    p4.add_argument("action", choices=["on", "off", "status"])
    sub.add_parser("self-backup", help="备份自身配置到远程（下一阶段）")
    p5 = sub.add_parser("export", help="导出应用配置")
    p5.add_argument("--app")
    p5.add_argument("--all", action="store_true")
    p5.add_argument("-o", "--output", required=True)
    p6 = sub.add_parser("import", help="导入应用配置")
    p6.add_argument("path")
    sub.add_parser("validate", help="校验所有应用/计划配置")
    p7 = sub.add_parser("script", help="生成备份/恢复一体脚本")
    p7.add_argument("--app", required=True)
    p7.add_argument("--plan-id", required=True)
    p7.add_argument("--flavor", choices=["ps1", "bat", "sh"], default="ps1")
    p7.add_argument("-o", "--output")
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
        "export": cmd_export,
        "import": cmd_import,
        "validate": cmd_validate,
        "script": cmd_script,
        "app": cmd_app,
    }
    return handlers[args.cmd](args)


if __name__ == "__main__":
    sys.exit(main())
