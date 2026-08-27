"""
code_analyzer.py

Two-stage pipeline:
  1. validate_code()   — AST whitelist check; raises CodeValidationError on failure
  2. analyze_code()    — extract access trace, feed to CacheSimulator, return full report

Access-trace extraction uses two modes selected automatically:
  • STATIC  — pure AST analysis for simple nested-for patterns (fast, no subprocess)
  • DYNAMIC — AST-instrumented subprocess execution for anything more complex

The `metadata` key in the returned dict is intentionally structured for LLM ingestion
in Phase 3 — it contains everything an LLM would need to explain the inefficiency.
"""

from __future__ import annotations

import ast
import json
import os
import subprocess
import sys
from dataclasses import dataclass

from cache_simulator import CacheSimulator

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

MAX_CODE_LENGTH = 1024  # bytes
MAX_LOOP_ITERS = 200    # per dimension when simulating statically — keeps trace ≤ 40 k
ELEMENT_SIZE = 4        # bytes (simulate int32 array elements)

ALLOWED_NODE_TYPES: frozenset = frozenset(
    {
        ast.Module,
        ast.Expr,
        ast.Assign,
        ast.AugAssign,
        ast.AnnAssign,
        ast.For,
        ast.While,
        ast.If,
        ast.IfExp,
        ast.Pass,
        ast.Break,
        ast.Continue,
        ast.Return,
        ast.FunctionDef,
        # Expressions
        ast.BinOp,
        ast.UnaryOp,
        ast.BoolOp,
        ast.Compare,
        ast.Constant,
        ast.Name,
        ast.List,
        ast.Tuple,
        ast.Subscript,
        ast.Slice,
        ast.Call,
        ast.ListComp,
        ast.GeneratorExp,
        ast.comprehension,
        # Operators
        ast.Add, ast.Sub, ast.Mult, ast.Div, ast.FloorDiv, ast.Mod, ast.Pow,
        ast.UAdd, ast.USub,
        ast.Eq, ast.NotEq, ast.Lt, ast.LtE, ast.Gt, ast.GtE,
        ast.And, ast.Or, ast.Not,
        ast.BitAnd, ast.BitOr, ast.BitXor, ast.LShift, ast.RShift,
        ast.Invert,
        # Context nodes
        ast.Load, ast.Store, ast.Del,
    }
)

ALLOWED_CALLS: frozenset = frozenset(
    {
        "range", "len", "int", "float", "str", "bool",
        "abs", "min", "max", "sum", "round",
        "enumerate", "zip", "reversed", "sorted",
        "isinstance", "type", "list",
    }
)

BANNED_NAMES: frozenset = frozenset(
    {
        "open", "eval", "exec", "compile", "__import__",
        "input", "print", "globals", "locals", "vars",
        "getattr", "setattr", "delattr", "hasattr",
        "breakpoint", "exit", "quit",
        "os", "sys", "subprocess", "socket", "urllib",
        "requests", "http", "io", "pathlib",
    }
)


# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------


class CodeValidationError(ValueError):
    """Raised when submitted code fails the whitelist check."""


# ---------------------------------------------------------------------------
# Validator
# ---------------------------------------------------------------------------


def validate_code(code: str) -> None:
    """
    Parse and walk the AST.  Raise CodeValidationError with a clear message
    on any disallowed construct.  Raise nothing on safe code.
    """
    if len(code.encode()) > MAX_CODE_LENGTH:
        raise CodeValidationError(
            f"Code too long: {len(code.encode())} bytes (max {MAX_CODE_LENGTH})."
        )

    try:
        tree = ast.parse(code)
    except SyntaxError as exc:
        raise CodeValidationError(f"Syntax error: {exc}") from exc

    for node in ast.walk(tree):
        node_type = type(node)

        if isinstance(node, (ast.Import, ast.ImportFrom)):
            raise CodeValidationError(
                "Imports are not allowed. Remove all import statements."
            )

        if node_type not in ALLOWED_NODE_TYPES:
            raise CodeValidationError(
                f"Disallowed construct: {node_type.__name__}. "
                "Only simple loops, assignments, and list operations are permitted."
            )

        if isinstance(node, ast.Call):
            func = node.func
            name = None
            if isinstance(func, ast.Name):
                name = func.id
            elif isinstance(func, ast.Attribute):
                raise CodeValidationError(
                    "Method calls (dot notation) are not allowed."
                )
            if name and name not in ALLOWED_CALLS:
                raise CodeValidationError(
                    f"Disallowed function call: '{name}'. "
                    f"Allowed: {sorted(ALLOWED_CALLS)}."
                )

        if isinstance(node, ast.Name) and node.id in BANNED_NAMES:
            raise CodeValidationError(
                f"Disallowed name: '{node.id}'."
            )

        if isinstance(node, ast.Attribute):
            raise CodeValidationError(
                "Attribute access (dot notation) is not allowed."
            )


# ---------------------------------------------------------------------------
# Static pattern extractor (no subprocess needed for simple cases)
# ---------------------------------------------------------------------------


@dataclass
class LoopInfo:
    var: str
    start: int
    stop: int
    step: int

    @property
    def iterations(self) -> range:
        return range(self.start, self.stop, self.step)


@dataclass
class StaticPattern:
    kind: str            # "nested_2d" | "flat_1d" | "complex"
    outer: LoopInfo | None = None
    inner: LoopInfo | None = None
    # For 2D: access indices into arr[outer_idx][inner_idx]
    outer_access_var: str | None = None
    inner_access_var: str | None = None
    array_name: str | None = None
    # For 1D strided
    stride: int = 1
    description: str = ""


def _try_extract_int(node: ast.expr) -> int | None:
    """Return an integer constant from a simple AST expression, or None."""
    if isinstance(node, ast.Constant) and isinstance(node.value, int):
        return node.value
    if isinstance(node, ast.UnaryOp) and isinstance(node.op, ast.USub):
        inner = _try_extract_int(node.operand)
        return -inner if inner is not None else None
    return None


def _parse_range_call(node: ast.Call) -> LoopInfo | None:
    """Extract (var_hint, start, stop, step) from range(...)."""
    if not (isinstance(node.func, ast.Name) and node.func.id == "range"):
        return None
    args = [_try_extract_int(a) for a in node.args]
    if len(args) == 1 and args[0] is not None:
        return LoopInfo("?", 0, args[0], 1)
    if len(args) == 2 and all(a is not None for a in args):
        return LoopInfo("?", args[0], args[1], 1)  # type: ignore[arg-type]
    if len(args) == 3 and all(a is not None for a in args):
        return LoopInfo("?", args[0], args[1], args[2])  # type: ignore[arg-type]
    return None


def _extract_subscript_vars(node: ast.expr) -> tuple[str, str] | None:
    """
    Given   arr[x][y]   return ("x", "y").
    Given   arr[x]      return ("x", None).
    """
    if isinstance(node, ast.Subscript):
        outer_val = node.value
        inner_idx = node.slice
        inner_name = inner_idx.id if isinstance(inner_idx, ast.Name) else None

        if isinstance(outer_val, ast.Subscript):
            deeper_idx = outer_val.slice
            outer_name = deeper_idx.id if isinstance(deeper_idx, ast.Name) else None
            arr_node = outer_val.value
            arr_name = arr_node.id if isinstance(arr_node, ast.Name) else None
            return (outer_name, inner_name) if outer_name and inner_name and arr_name else None
        if isinstance(outer_val, ast.Name) and inner_name:
            return (None, inner_name)
    return None


def _walk_stmts(body: list[ast.stmt]):
    """
    Yield every node reachable from a list of statements, without wrapping
    them in a throwaway ast.Module (which required a fresh construction +
    full re-walk on every call site). Equivalent to
    ast.walk(ast.Module(body=body, type_ignores=[])) minus the Module node
    itself, which callers here never cared about anyway.
    """
    for stmt in body:
        yield from ast.walk(stmt)


def _find_nested_loops(tree: ast.AST) -> StaticPattern | None:
    """
    Detect the most common patterns:
      for i in range(N):
          for j in range(M):
              ... arr[i][j] ... or ... arr[j][i] ...
    """
    for outer_for in ast.walk(tree):
        if not isinstance(outer_for, ast.For):
            continue
        if not isinstance(outer_for.iter, ast.Call):
            continue
        outer_loop = _parse_range_call(outer_for.iter)
        if outer_loop is None:
            continue
        if not isinstance(outer_for.target, ast.Name):
            continue
        outer_var = outer_for.target.id
        outer_loop.var = outer_var

        for inner_for in _walk_stmts(outer_for.body):
            if not isinstance(inner_for, ast.For):
                continue
            if not isinstance(inner_for.iter, ast.Call):
                continue
            inner_loop = _parse_range_call(inner_for.iter)
            if inner_loop is None:
                continue
            if not isinstance(inner_for.target, ast.Name):
                continue
            inner_var = inner_for.target.id
            inner_loop.var = inner_var

            # Search for subscript accesses in inner loop body
            for stmt in _walk_stmts(inner_for.body):
                # Check Assign targets and value for subscripts
                targets: list[ast.expr] = []
                if isinstance(stmt, ast.Assign):
                    targets = list(stmt.targets) + [stmt.value]
                elif isinstance(stmt, ast.AugAssign):
                    targets = [stmt.target, stmt.value]
                elif isinstance(stmt, ast.Expr):
                    targets = [stmt.value]

                for sub_node in targets:
                    for candidate in ast.walk(sub_node) if not isinstance(sub_node, ast.expr) else [sub_node]:
                        if not isinstance(candidate, ast.Subscript):
                            continue
                        if not isinstance(candidate.value, ast.Subscript):
                            continue
                        arr_node = candidate.value.value
                        if not isinstance(arr_node, ast.Name):
                            continue
                        row_idx = candidate.value.slice
                        col_idx = candidate.slice
                        if not (isinstance(row_idx, ast.Name) and isinstance(col_idx, ast.Name)):
                            continue

                        row_var = row_idx.id
                        col_var = col_idx.id

                        if {row_var, col_var} != {outer_var, inner_var}:
                            continue

                        return StaticPattern(
                            kind="nested_2d",
                            outer=outer_loop,
                            inner=inner_loop,
                            outer_access_var=row_var,
                            inner_access_var=col_var,
                            array_name=arr_node.id,
                        )

    return None


def _find_flat_loop(tree: ast.AST) -> StaticPattern | None:
    """Detect a simple flat loop:  for i in range(N, [M,] [step]):  arr[i]"""
    for for_node in ast.walk(tree):
        if not isinstance(for_node, ast.For):
            continue
        if not isinstance(for_node.iter, ast.Call):
            continue
        loop = _parse_range_call(for_node.iter)
        if loop is None:
            continue
        if not isinstance(for_node.target, ast.Name):
            continue
        var = for_node.target.id
        loop.var = var

        for stmt in for_node.body:
            for candidate in ast.walk(stmt):
                if not isinstance(candidate, ast.Subscript):
                    continue
                if not isinstance(candidate.value, ast.Name):
                    continue
                idx = candidate.slice
                if isinstance(idx, ast.Name) and idx.id == var:
                    return StaticPattern(
                        kind="flat_1d",
                        outer=loop,
                        array_name=candidate.value.id,
                        stride=loop.step,
                        description=f"flat 1D loop over '{candidate.value.id}', stride={loop.step}",
                    )
    return None


def extract_static_pattern(code: str) -> StaticPattern:
    """Try static extraction; returns a 'complex' pattern if none matched."""
    tree = ast.parse(code)
    pattern = _find_nested_loops(tree) or _find_flat_loop(tree)
    if pattern:
        return pattern
    return StaticPattern(kind="complex", description="complex pattern — requires dynamic analysis")


# ---------------------------------------------------------------------------
# Trace generation from static pattern
# ---------------------------------------------------------------------------


def generate_trace_from_pattern(
    pattern: StaticPattern, rows: int = 0, cols: int = 0
) -> list[int]:
    """
    Convert a StaticPattern into a list of byte addresses.
    rows / cols override pattern loop bounds if provided.
    """
    if pattern.kind == "nested_2d":
        outer = pattern.outer
        inner = pattern.inner
        assert outer and inner
        num_rows = rows or min(len(outer.iterations), MAX_LOOP_ITERS)
        num_cols = cols or min(len(inner.iterations), MAX_LOOP_ITERS)

        addresses: list[int] = []
        outer_range = range(min(len(outer.iterations), num_rows))
        inner_range = range(min(len(inner.iterations), num_cols))

        for oi in outer_range:
            for ii in inner_range:
                # Map loop iteration index back to actual loop variable values
                i_val = outer.start + oi * outer.step
                j_val = inner.start + ii * inner.step
                # Determine row/col from access pattern (arr[row_var][col_var])
                row_val = i_val if pattern.outer_access_var == outer.var else j_val
                col_val = j_val if pattern.outer_access_var == outer.var else i_val
                # Ignore: actual_cols for stride calculation uses inner loop length
                stride_cols = len(inner.iterations)
                flat = row_val * stride_cols + col_val
                addresses.append(flat * ELEMENT_SIZE)

        return addresses

    if pattern.kind == "flat_1d":
        outer = pattern.outer
        assert outer
        limit = min(len(outer.iterations), MAX_LOOP_ITERS)
        return [
            (outer.start + i * outer.step) * ELEMENT_SIZE
            for i in range(limit)
        ]

    return []


# ---------------------------------------------------------------------------
# Dynamic execution via sandboxed subprocess
# ---------------------------------------------------------------------------


def run_sandboxed(code: str, timeout: float = 3.0) -> list[tuple]:
    """
    Execute code in an isolated subprocess (sandbox_worker.py).
    Returns the raw access log as a list of [obj_id, index, op] triples.
    Raises RuntimeError on failure / timeout.
    """
    worker_path = os.path.join(os.path.dirname(__file__), "sandbox_worker.py")

    try:
        result = subprocess.run(
            [sys.executable, "-I", worker_path],
            input=code,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
    except subprocess.TimeoutExpired as exc:
        raise RuntimeError(
            f"Code execution timed out after {timeout:.0f} seconds."
        ) from exc
    except Exception as exc:
        raise RuntimeError(f"Subprocess launch failed: {exc}") from exc

    if result.returncode != 0:
        stderr = (result.stderr or "").strip()[:400]
        raise RuntimeError(f"Worker exited with code {result.returncode}: {stderr}")

    stdout = result.stdout.strip()
    if not stdout:
        raise RuntimeError("Worker produced no output.")

    try:
        data = json.loads(stdout)
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"Worker output is not valid JSON: {exc}") from exc

    if not data.get("ok"):
        raise RuntimeError(data.get("error", "Unknown worker error."))

    return data["accesses"]


def _reconstruct_2d_addresses(raw_accesses: list[tuple]) -> list[int]:
    """
    Convert raw (obj_id, index, op) triples into flat byte addresses.

    For arr[i][j], each data access emits two consecutive log entries:
        (outer_id, row, "get")   <- arr[i]
        (inner_id, col, "set")   <- arr[i][j] = …
    We exploit this invariant to build an inner_obj_id -> row mapping,
    then compute  flat = row * num_cols + col.

    Falls back to 1D if no 2D structure is detected.
    """
    if not raw_accesses:
        return []

    # Step 1: outer array = first object ever accessed in the log
    outer_id = raw_accesses[0][0]

    # Step 2: build inner_obj -> row via consecutive-pair scanning.
    # After every (outer_id, row, "get") the very next entry is always
    # (inner_row_obj, col, op) — Python evaluates arr[i] before arr[i][j].
    inner_id_to_row: dict[int, int] = {}
    for k in range(len(raw_accesses) - 1):
        oid, idx = raw_accesses[k][0], raw_accesses[k][1]
        if oid == outer_id:
            next_oid = raw_accesses[k + 1][0]
            if next_oid != outer_id:
                inner_id_to_row[next_oid] = idx  # may overwrite with same value — ok

    if not inner_id_to_row:
        # No 2D structure detected; treat as 1D
        return [entry[1] * ELEMENT_SIZE for entry in raw_accesses]

    # Step 3: num_cols = max column index seen in any inner-array access + 1
    num_cols = (
        max(
            entry[1]
            for entry in raw_accesses
            if entry[0] in inner_id_to_row
        )
        + 1
    )

    # Step 4: emit flat byte addresses for data accesses (inner arrays only)
    return [
        (inner_id_to_row[entry[0]] * num_cols + entry[1]) * ELEMENT_SIZE
        for entry in raw_accesses
        if entry[0] in inner_id_to_row
    ]


# ---------------------------------------------------------------------------
# Metadata builder (clean output for LLM in Phase 3)
# ---------------------------------------------------------------------------


def build_metadata(pattern: StaticPattern, stats: dict) -> dict:
    """
    Build the structured metadata dict that Phase 3 will feed to an LLM.
    All keys are intentionally human-readable strings.
    """
    issues: list[str] = []
    suggestions: list[str] = []

    if pattern.kind == "nested_2d":
        outer = pattern.outer
        inner = pattern.inner
        assert outer and inner

        is_row_major = (
            pattern.outer_access_var == outer.var
            and pattern.inner_access_var == inner.var
        )

        outer_dim = len(outer.iterations)
        inner_dim = len(inner.iterations)
        access_order = "row-major" if is_row_major else "column-major"

        if not is_row_major:
            issues.append(
                "Column-major traversal: the inner loop variable iterates over rows, "
                "causing cache-line evictions on every inner iteration."
            )
            suggestions.append(
                "Swap the loop order so the inner loop iterates over columns: "
                f"for {outer.var} in range({inner_dim}): for {inner.var} in range({outer_dim}): arr[{inner.var}][{outer.var}]"
            )

        if stats["hit_rate"] < 0.5:
            issues.append(
                f"Very low cache hit rate ({stats['hit_rate']:.1%}) — "
                "most memory accesses miss the cache."
            )

        locality = "good spatial" if is_row_major else "poor spatial"

        return {
            "pattern_type": "nested_2d_loop",
            "access_order": access_order,
            "loop_depth": 2,
            "loop_variables": [
                {"name": outer.var, "start": outer.start, "stop": outer.stop, "step": outer.step},
                {"name": inner.var, "start": inner.start, "stop": inner.stop, "step": inner.step},
            ],
            "array_name": pattern.array_name,
            "array_dimensions": [outer_dim, inner_dim],
            "inner_loop_varies": "columns" if is_row_major else "rows",
            "locality": locality,
            "cache_efficiency": (
                "high" if stats["hit_rate"] > 0.8
                else "medium" if stats["hit_rate"] > 0.4
                else "low"
            ),
            "issues": issues,
            "suggestions": suggestions,
            "summary": (
                f"2D nested loop over a {outer_dim}×{inner_dim} matrix "
                f"in {access_order} order."
            ),
        }

    if pattern.kind == "flat_1d":
        outer = pattern.outer
        assert outer
        step = outer.step
        is_strided = step != 1

        if is_strided and step > 1:
            issues.append(
                f"Stride-{step} access pattern: skipping {step - 1} elements on each "
                "iteration reduces spatial locality and increases cache misses."
            )
            suggestions.append("Use sequential (stride-1) access where possible.")

        return {
            "pattern_type": "flat_1d_loop",
            "access_order": "strided" if is_strided else "sequential",
            "loop_depth": 1,
            "loop_variables": [
                {"name": outer.var, "start": outer.start, "stop": outer.stop, "step": outer.step}
            ],
            "array_name": pattern.array_name,
            "stride": step,
            "locality": "poor spatial" if is_strided else "good spatial",
            "cache_efficiency": (
                "high" if stats["hit_rate"] > 0.8
                else "medium" if stats["hit_rate"] > 0.4
                else "low"
            ),
            "issues": issues,
            "suggestions": suggestions,
            "summary": (
                f"1D loop with stride {step} over '{pattern.array_name}'."
            ),
        }

    return {
        "pattern_type": "complex",
        "access_order": "unknown",
        "loop_depth": "unknown",
        "loop_variables": [],
        "locality": "unknown",
        "cache_efficiency": (
            "high" if stats["hit_rate"] > 0.8
            else "medium" if stats["hit_rate"] > 0.4
            else "low"
        ),
        "issues": ["Pattern too complex for static analysis."],
        "suggestions": [],
        "summary": "Complex access pattern — static analysis was not sufficient.",
    }


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def analyze_code(
    code: str,
    cache_size_bytes: int = 512,
    block_size_bytes: int = 64,
    associativity: int = 2,
    max_log: int = 256,
    include_debug: bool = False,
) -> dict:
    """
    Full pipeline:
      validate → extract pattern → generate trace → simulate → return report

    Returns a dict suitable for JSON serialisation; raises CodeValidationError
    on invalid code, RuntimeError on execution failure.
    """
    validate_code(code)

    pattern = extract_static_pattern(code)
    analysis_mode = "static"

    if pattern.kind == "complex":
        try:
            raw = run_sandboxed(code)
            addresses = _reconstruct_2d_addresses(raw)
            analysis_mode = "dynamic"
        except RuntimeError:
            addresses = []
    else:
        addresses = generate_trace_from_pattern(pattern)

    sim = CacheSimulator(
        cache_size_bytes=cache_size_bytes,
        block_size_bytes=block_size_bytes,
        associativity=associativity,
    )
    sim.access_many(addresses)
    stats = sim.stats()
    metadata = build_metadata(pattern, stats)

    result: dict = {
        "analysis_mode": analysis_mode,
        "total_addresses_traced": len(addresses),
        "cache_stats": stats,
        "access_log": sim.access_log_as_dicts(max_records=max_log),
        "metadata": metadata,
        "pattern": {
            "kind": pattern.kind,
            "description": pattern.description or metadata.get("summary", ""),
            "array_name": pattern.array_name,
        },
    }
    if include_debug:
        result["debug_info"] = {
            "first_50_addresses": addresses[:50],
            "total_addresses_generated": len(addresses),
            "analysis_mode": analysis_mode,
            "pattern_kind": pattern.kind,
        }
    return result
