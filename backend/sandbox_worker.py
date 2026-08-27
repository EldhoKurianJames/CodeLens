"""
Sandbox worker — executed as a subprocess by code_analyzer.py.

Receives user code on stdin as plain text.
Outputs a single JSON line to stdout:
  {"ok": true,  "accesses": [[obj_id, index, "get"|"set"], ...]}
  {"ok": false, "error": "<message>"}

Security layers applied here (after AST validation already passed in the parent):
  1. Restricted __builtins__ — no open/eval/exec/__import__
  2. _TL wrapper injected so every list subscript is logged
  3. AST transformer replaces list literals & list-comps with _TL(...)
  4. subprocess.run(timeout=3) in parent kills us if we hang
  5. On POSIX: RLIMIT_AS caps memory to 128 MB, RLIMIT_CPU caps CPU time to
     2 seconds so a `while True: pass` is killed by the OS almost
     immediately instead of running for the full 3-second wall-clock
     subprocess timeout.
  6. Cross-platform (Windows-safe) defense in depth: every `while` loop's
     condition check is instrumented (same ast.NodeTransformer pattern used
     for _TL) to increment a global counter, and a RuntimeError is raised
     once it crosses ITERATION_LIMIT. RLIMIT_CPU is POSIX-only, so this is
     the only hard stop against infinite loops on Windows; it is applied
     unconditionally on every platform as a second line of defense even
     where RLIMIT_CPU is available (e.g. a loop that is CPU-cheap per
     iteration but never terminates due to a logic bug that isn't a tight
     spin — RLIMIT_CPU would still catch it, but the counter catches it
     deterministically regardless of CPU speed).
"""

from __future__ import annotations

import ast
import json
import sys

# ── POSIX resource limits (no-op on Windows) ─────────────────────────────────
try:
    import resource  # type: ignore

    _128MB = 128 * 1024 * 1024
    resource.setrlimit(resource.RLIMIT_AS, (_128MB, _128MB))

    # Hard CPU-time cap: 2 seconds. Catches tight infinite loops (e.g.
    # `while True: pass`) almost instantly instead of waiting for the
    # parent's 3-second wall-clock subprocess timeout to kill us.
    resource.setrlimit(resource.RLIMIT_CPU, (2, 2))
except (ImportError, AttributeError, ValueError):
    pass

# ── Cross-platform iteration cap (defense in depth, see module docstring) ────
ITERATION_LIMIT = 500_000
_iteration_counter = [0]

# ── Access log shared state ───────────────────────────────────────────────────
_access_log: list[tuple] = []


class _TL(list):
    """Tracked list.  Wraps list literals so subscript accesses are recorded."""

    def __init__(self, data=(), _depth: int = 0) -> None:
        self._depth = _depth
        self._my_id = id(self)
        processed: list = []
        for item in data:
            if isinstance(item, list) and not isinstance(item, _TL):
                processed.append(_TL(item, _depth=_depth + 1))
            else:
                processed.append(item)
        super().__init__(processed)

    def __mul__(self, n: int) -> _TL:
        return _TL(list.__mul__(list(self), n), _depth=self._depth)

    def __rmul__(self, n: int) -> _TL:
        return self.__mul__(n)

    def __getitem__(self, idx):
        val = list.__getitem__(self, idx)
        if isinstance(idx, int):
            _access_log.append((self._my_id, idx, "get"))
        return val

    def __setitem__(self, idx, val):
        if isinstance(idx, int):
            _access_log.append((self._my_id, idx, "set"))
        list.__setitem__(self, idx, val)


def _tick_iteration_limit() -> bool:
    """
    Called once per `while` condition evaluation (injected by _ListWrapper).
    Raises once the global iteration count crosses ITERATION_LIMIT — the
    Windows-safe, platform-independent backstop against infinite loops
    described in the module docstring.
    """
    _iteration_counter[0] += 1
    if _iteration_counter[0] > ITERATION_LIMIT:
        raise RuntimeError(
            f"Iteration limit exceeded ({ITERATION_LIMIT:,} while-condition "
            "checks) — likely an infinite loop."
        )
    return True


# ── AST transformer: wrap List / ListComp nodes with _TL(...); guard while ──


class _ListWrapper(ast.NodeTransformer):
    def visit_List(self, node: ast.List) -> ast.expr:
        self.generic_visit(node)
        return ast.Call(
            func=ast.Name(id="_TL", ctx=ast.Load()),
            args=[node],
            keywords=[],
        )

    def visit_ListComp(self, node: ast.ListComp) -> ast.expr:
        self.generic_visit(node)
        return ast.Call(
            func=ast.Name(id="_TL", ctx=ast.Load()),
            args=[node],
            keywords=[],
        )

    def visit_While(self, node: ast.While) -> ast.While:
        self.generic_visit(node)
        # Rewrite `while <test>:` -> `while _TICK() and (<test>):` so every
        # condition check is counted, regardless of platform.
        guarded_test = ast.BoolOp(
            op=ast.And(),
            values=[
                ast.Call(func=ast.Name(id="_TICK", ctx=ast.Load()), args=[], keywords=[]),
                node.test,
            ],
        )
        node.test = guarded_test
        return node


# ── Restricted builtins ───────────────────────────────────────────────────────

_SAFE_BUILTINS: dict = {
    name: getattr(__builtins__, name, __builtins__[name] if isinstance(__builtins__, dict) else None)  # type: ignore[index]
    for name in (
        "range", "len", "int", "float", "str", "bool",
        "abs", "min", "max", "sum", "round",
        "enumerate", "zip", "reversed", "sorted",
        "isinstance", "type",
        "True", "False", "None",
        "print",
    )
    if hasattr(__builtins__, name)
    or (isinstance(__builtins__, dict) and name in __builtins__)
}

# Ensure critical builtins that may not be attributes are present
for _name in ("range", "len", "int", "float", "str", "bool",
              "abs", "min", "max", "sum", "round",
              "enumerate", "zip", "reversed", "sorted",
              "isinstance", "type", "print"):
    if _name not in _SAFE_BUILTINS:
        _SAFE_BUILTINS[_name] = eval(_name)  # noqa: S307 — only built-in names

_SAFE_BUILTINS["True"] = True
_SAFE_BUILTINS["False"] = False
_SAFE_BUILTINS["None"] = None


# ── Main ──────────────────────────────────────────────────────────────────────

def _main() -> None:
    user_code = sys.stdin.read()

    try:
        tree = ast.parse(user_code, filename="<user>")
    except SyntaxError as exc:
        print(json.dumps({"ok": False, "error": f"SyntaxError: {exc}"}))
        return

    tree = _ListWrapper().visit(tree)
    ast.fix_missing_locations(tree)

    try:
        code_obj = compile(tree, "<user>", "exec")
    except Exception as exc:
        print(json.dumps({"ok": False, "error": f"CompileError: {exc}"}))
        return

    ns: dict = {
        "__builtins__": _SAFE_BUILTINS,
        "_TL": _TL,
        "_TICK": _tick_iteration_limit,
        "_access_log": _access_log,
    }

    try:
        exec(code_obj, ns)  # noqa: S102
    except Exception as exc:
        print(json.dumps({"ok": False, "error": f"RuntimeError: {exc}"}))
        return

    print(json.dumps({"ok": True, "accesses": _access_log}))


if __name__ == "__main__":
    _main()
