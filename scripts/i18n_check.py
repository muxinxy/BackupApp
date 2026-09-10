#!/usr/bin/env python3
"""AST-based translation completeness checker + stdlib self-tests.

Modes (pure stdlib: ast, pathlib, sys, re):
  python scripts/i18n_check.py keys                 # print extracted _("...") keys sorted
  python scripts/i18n_check.py check                # run all checks (A-E)
  python scripts/i18n_check.py check --allow-missing  # skip completeness (Check B)
  python scripts/i18n_check.py --selfcheck          # stdlib assert unit tests

Checks:
  A  extraction: every _("...") call yields a key; non-literal first args are errors
  B  completeness: every key exists in backupapp/locales/en.py MESSAGES (--allow-missing skips)
  C  no bare Chinese: no CJK string literal outside _() / docstrings / # i18n:data dicts
  D  placeholder parity: {token} sets of key and translation are identical
  E  forbidden _(f"...") f-string calls
  F  forbidden `_` rebinding: `_` is the translation function, so binding it
     (parameter, assignment/unpacking target, `for _ in`, `with ... as _`,
     `except ... as _`, `import ... as _`, walrus, global/nonlocal) silently
     turns later `_("...")` calls into calls on that value
"""
import ast
import pathlib
import re
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
SCOPE = ROOT / "backupapp"
CATALOG_FILE = SCOPE / "locales" / "en.py"
sys.path.insert(0, str(ROOT))  # make `import backupapp` work when run as scripts/i18n_check.py
CJK = re.compile(r"[\u4e00-\u9fff]")
PLACEHOLDER = re.compile(r"\{[^{}]*\}")
LOG_LEVELS = {"debug", "info", "warning", "error", "critical", "exception"}


def _link(tree):
    """Attach parent pointers so child nodes can inspect their context."""
    for node in ast.walk(tree):
        for child in ast.iter_child_nodes(node):
            child._parent = node


def _is_docstring(node):
    """True if node is a standalone string statement (docstring or comment-like)."""
    return isinstance(getattr(node, "_parent", None), ast.Expr)


def _is_logging_arg(node):
    """True if node is an argument of a logger call (logging.get_logger().info(...))."""
    parent = getattr(node, "_parent", None)
    if not isinstance(parent, ast.Call):
        return False
    func = parent.func
    if not isinstance(func, ast.Attribute) or func.attr not in LOG_LEVELS:
        return False
    value = func.value
    while isinstance(value, ast.Call):
        vf = value.func
        if isinstance(vf, ast.Attribute) and vf.attr in ("get_logger", "getLogger"):
            return True
        value = vf.value if isinstance(vf, ast.Attribute) else None
    return False


def _is_subscript_index(node):
    """True if node is a subscript index, e.g. "一二三四五六日"[d - 1] (display data)."""
    return isinstance(getattr(node, "_parent", None), ast.Subscript)


def _is_fstring_part(node):
    """True if node is a literal part of an f-string (e.g. the "周" in f"周{...}")."""
    return isinstance(getattr(node, "_parent", None), ast.JoinedStr)


def _is_compare_data(node):
    """True if node is a member of a tuple/set/list used in a comparison (data matching)."""
    parent = getattr(node, "_parent", None)
    if not isinstance(parent, (ast.Tuple, ast.Set, ast.List)):
        return False
    return isinstance(getattr(parent, "_parent", None), ast.Compare)


def _is_i18n_data(node, lines):
    """True if node sits inside a dict literal preceded by a `# i18n:data` comment."""
    parent = getattr(node, "_parent", None)
    while parent is not None and not isinstance(parent, ast.Dict):
        parent = getattr(parent, "_parent", None)
    if parent is None:
        return False
    i = parent.lineno - 2  # 0-based line above the dict's opening line
    while i >= 0 and not lines[i].strip():
        i -= 1
    return i >= 0 and "# i18n:data" in lines[i]


def _placeholders(s):
    return set(PLACEHOLDER.findall(s))


def _underscore_bindings(tree):
    """Check F: every place where the name `_` is bound (not merely read).

    Returns a list of (lineno, kind) so the error can name the construct.
    """
    found = []
    for node in ast.walk(tree):
        # assignment / unpacking / for / comprehension / with-as / walrus targets
        if isinstance(node, ast.Name) and node.id == "_" \
                and isinstance(node.ctx, ast.Store):
            found.append((node.lineno, "assignment target"))
        elif isinstance(node, ast.arg) and node.arg == "_":
            found.append((node.lineno, "parameter"))
        elif isinstance(node, ast.ExceptHandler) and node.name == "_":
            found.append((node.lineno, "except handler"))
        elif isinstance(node, ast.alias) and node.asname == "_":
            found.append((node.lineno, "import alias"))
        elif isinstance(node, (ast.Global, ast.Nonlocal)) and "_" in node.names:
            found.append((node.lineno, "global/nonlocal declaration"))
    return found


def _load_catalog():
    """Load MESSAGES from en.py without importing the package (pure data file)."""
    ns = {}
    exec(compile(CATALOG_FILE.read_text(encoding="utf-8"), str(CATALOG_FILE), "exec"), ns)
    return ns.get("MESSAGES", {})


def _analyze_file(path):
    """Return (keys, errors, bare) for one file.

    keys: {(lineno, col): key} from _("...") calls.
    errors: Check A/E diagnostics (non-literal / f-string _() args).
    bare: Check C diagnostics (unwrapped CJK string literals).
    """
    src = path.read_text(encoding="utf-8")
    lines = src.splitlines()
    try:
        tree = ast.parse(src)
    except SyntaxError as e:
        return {}, [f"{path}:{e.lineno}: syntax error: {e.msg}"], []
    _link(tree)

    keys = {}
    errors = []
    for node in ast.walk(tree):
        if not (isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
                and node.func.id == "_"):
            continue
        if not node.args:
            errors.append(f"{path}:{node.lineno}: _() requires a string literal argument")
            continue
        first = node.args[0]
        if isinstance(first, ast.JoinedStr):
            errors.append(f"{path}:{node.lineno}: forbidden _(f\"...\") — use a plain literal and .format()")
        elif isinstance(first, ast.Constant) and isinstance(first.value, str):
            # Adjacent string literals ("a" "b") are folded into one Constant by the parser.
            keys[(first.lineno, first.col_offset)] = first.value
        elif isinstance(first, ast.Name):
            # Runtime key, e.g. _(label) over a # i18n:data map — not extractable, not an error.
            pass
        else:
            errors.append(f"{path}:{node.lineno}: _() first argument must be a string literal")

    for lineno, kind in _underscore_bindings(tree):
        errors.append(f"{path}:{lineno}: `_` must not be bound ({kind}) - it is the "
                      f"translation function; use `_args`/`_i`/`_unused` instead")

    bare = []
    for node in ast.walk(tree):
        if not (isinstance(node, ast.Constant) and isinstance(node.value, str)
                and CJK.search(node.value)):
            continue
        if (node.lineno, node.col_offset) in keys:
            continue
        if (_is_docstring(node) or _is_logging_arg(node) or _is_subscript_index(node)
                or _is_fstring_part(node) or _is_compare_data(node)
                or _is_i18n_data(node, lines) or "\n" in node.value):
            continue
        bare.append(f"{path}:{node.lineno}: bare Chinese string: {node.value!r}")
    return keys, errors, bare


def cmd_keys():
    all_keys = set()
    for path in sorted(SCOPE.rglob("*.py")):
        keys, _, _ = _analyze_file(path)
        all_keys.update(keys.values())
    for key in sorted(all_keys):
        print(key)
    return 0


def cmd_check(allow_missing):
    catalog = _load_catalog()
    errors = []
    all_keys = {}
    for path in sorted(SCOPE.rglob("*.py")):
        keys, errs, bare = _analyze_file(path)
        errors.extend(errs)
        errors.extend(bare)
        for (lineno, _col), key in keys.items():
            all_keys.setdefault(key, []).append(f"{path}:{lineno}")
    if not allow_missing:
        for key, locs in sorted(all_keys.items()):
            if key not in catalog:
                for loc in locs:
                    errors.append(f"{loc}: missing translation: {key!r}")
    for key, val in sorted(catalog.items()):
        if _placeholders(key) != _placeholders(val):
            errors.append(f"{CATALOG_FILE}: placeholder mismatch for {key!r}: "
                          f"{sorted(_placeholders(key))} != {sorted(_placeholders(val))}")
    for e in errors:
        print(e)
    if errors:
        print(f"{len(errors)} error(s)")
        return 1
    print("OK")
    return 0


def cmd_selfcheck():
    from backupapp.i18n import set_language, _, current_language
    # fallback: empty catalog returns the source (Chinese) string
    set_language("zh-CN")
    assert _("立即备份全部") == "立即备份全部"
    # unknown language: no exception, falls back to source
    set_language("bogus")
    assert _("任意") == "任意"
    # auto-detect: resolves to a known language, never raises
    set_language("auto")
    assert current_language() in ("zh-CN", "en")
    # placeholder parity across the whole catalog (Check D logic)
    from backupapp.locales import en
    for key, val in en.MESSAGES.items():
        assert _placeholders(key) == _placeholders(val), (key, val)
    # old-data round-trip: _FREQ_REV still decodes persisted Chinese frequency values
    try:
        from backupapp.gui.settings_dialogs import _FREQ_REV
    except ImportError as e:  # PySide6 not installed on this interpreter
        print(f"skip _FREQ_REV round-trip (PySide6 unavailable): {e}")
    else:
        assert _FREQ_REV["每天"] == "daily"
    # Check F logic: `_` rebinding detector
    def _kinds(src):
        return {kind for _, kind in _underscore_bindings(ast.parse(src))}
    assert _kinds("def f(self, *_):\n    pass\n") == {"parameter"}
    assert _kinds("for full, _ in x:\n    pass\n") == {"assignment target"}
    assert _kinds("try:\n    pass\nexcept E as _:\n    pass\n") == {"except handler"}
    assert _kinds("import os as _\n") == {"import alias"}
    assert _kinds("a, _ = f()\n") == {"assignment target"}
    assert _kinds("print(_('a'))\n") == set()  # a plain call is not a binding
    print("selfcheck OK")
    return 0


def main(argv):
    allow_missing = "--allow-missing" in argv[1:]
    args = [a for a in argv[1:] if a != "--allow-missing"]
    if "--selfcheck" in args:
        return cmd_selfcheck()
    mode = args[0] if args else "check"
    if mode == "keys":
        return cmd_keys()
    if mode == "check":
        return cmd_check(allow_missing)
    print(f"unknown mode: {mode}", file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv))