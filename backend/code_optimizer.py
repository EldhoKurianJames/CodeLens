"""
code_optimizer.py — Feature: auto-optimizer with re-simulation.

Detects ONE well-understood cache antipattern via AST analysis and generates a
concretely transformed version, then re-runs BOTH versions through the existing
analyzer + simulator pipeline to prove the fix works with real simulated numbers.

Supported transformation
------------------------
LOOP INTERCHANGE for 2D matrix access:

    for j in range(N):          # outer loop over columns
        for i in range(N):      # inner loop over rows
            arr[i][j] = ...     # row index = INNER var  ->  column-major access!

The antipattern: the ROW subscript (first index) is driven by the INNER loop
variable, so consecutive iterations jump a whole row-width in memory
(stride = num_cols * 4 bytes), destroying spatial locality.

The fix: swap the two loop headers (targets + iterables), leaving the body and
all other logic identical. After the swap the row index is driven by the OUTER
loop, giving sequential (stride-1) access within each row.

Safety conditions checked before transforming:
  - both loops are simple `for <name> in range(...)` statements
  - the inner loop's range() arguments do not reference the outer loop variable
    (interchange would change semantics otherwise)
  - a subscript `arr[inner_var][outer_var]` actually exists in the inner body
"""

from __future__ import annotations

import ast
import copy
from dataclasses import dataclass

from code_analyzer import analyze_code

# ---------------------------------------------------------------------------
# Detection
# ---------------------------------------------------------------------------


@dataclass
class InterchangeCandidate:
    """Everything needed to describe and apply one loop-interchange."""
    outer_var: str
    inner_var: str
    array_name: str
    outer_lineno: int
    inner_lineno: int
    transformed_code: str


def _is_simple_range_for(node: ast.For) -> bool:
    """True if node is `for <Name> in range(...)`."""
    return (
        isinstance(node.target, ast.Name)
        and isinstance(node.iter, ast.Call)
        and isinstance(node.iter.func, ast.Name)
        and node.iter.func.id == "range"
    )


def _range_args_reference(node: ast.Call, var_name: str) -> bool:
    """True if any range() argument references the given variable name."""
    for arg in node.args:
        for sub in ast.walk(arg):
            if isinstance(sub, ast.Name) and sub.id == var_name:
                return True
    return False


def _find_bad_2d_access(
    body: list[ast.stmt], row_var: str, col_var: str
) -> str | None:
    """
    Search statements for a 2-level subscript  arr[row_var][col_var].
    Returns the array name if found, else None.
    """
    for stmt in body:
        for node in ast.walk(stmt):
            if not isinstance(node, ast.Subscript):
                continue
            if not isinstance(node.value, ast.Subscript):
                continue
            arr_node = node.value.value
            row_idx = node.value.slice
            col_idx = node.slice
            if not isinstance(arr_node, ast.Name):
                continue
            if not (isinstance(row_idx, ast.Name) and isinstance(col_idx, ast.Name)):
                continue
            if row_idx.id == row_var and col_idx.id == col_var:
                return arr_node.id
    return None


def detect_loop_interchange(code: str) -> InterchangeCandidate | None:
    """
    Detect the column-major-inside-row-major-loop antipattern:
    outer loop var used as the SECOND (column) index, inner loop var used as
    the FIRST (row) index.

    Returns an InterchangeCandidate with ready-to-use transformed code,
    or None if the pattern is not present.
    """
    try:
        tree = ast.parse(code)
    except SyntaxError:
        return None

    for outer_for in ast.walk(tree):
        if not isinstance(outer_for, ast.For) or not _is_simple_range_for(outer_for):
            continue
        outer_var = outer_for.target.id  # type: ignore[union-attr]

        for inner_for in ast.walk(
            ast.Module(body=outer_for.body, type_ignores=[])
        ):
            if not isinstance(inner_for, ast.For) or not _is_simple_range_for(inner_for):
                continue
            inner_var = inner_for.target.id  # type: ignore[union-attr]
            if inner_var == outer_var:
                continue

            # Safety: inner loop bounds must not depend on the outer variable
            if _range_args_reference(inner_for.iter, outer_var):  # type: ignore[arg-type]
                continue

            # Antipattern: arr[INNER][OUTER] — row driven by inner loop
            array_name = _find_bad_2d_access(inner_for.body, inner_var, outer_var)
            if array_name is None:
                continue

            transformed = _apply_interchange(code, outer_for.lineno, inner_for.lineno)
            if transformed is None:
                continue

            return InterchangeCandidate(
                outer_var=outer_var,
                inner_var=inner_var,
                array_name=array_name,
                outer_lineno=outer_for.lineno,
                inner_lineno=inner_for.lineno,
                transformed_code=transformed,
            )

    return None


# ---------------------------------------------------------------------------
# Transformation
# ---------------------------------------------------------------------------


def _apply_interchange(
    code: str, outer_lineno: int, inner_lineno: int
) -> str | None:
    """
    Re-parse the code, locate the two For nodes by line number, and swap their
    loop headers (target + iter) in-place. Everything else — the body, other
    statements, ordering — stays identical. Returns the unparsed source.
    """
    tree = ast.parse(code)
    outer_node: ast.For | None = None
    inner_node: ast.For | None = None

    for node in ast.walk(tree):
        if isinstance(node, ast.For):
            if node.lineno == outer_lineno:
                outer_node = node
            elif node.lineno == inner_lineno:
                inner_node = node

    if outer_node is None or inner_node is None:
        return None

    # Swap loop headers; deep-copy to avoid shared-node aliasing in the AST
    outer_target, outer_iter = copy.deepcopy(outer_node.target), copy.deepcopy(outer_node.iter)
    outer_node.target = copy.deepcopy(inner_node.target)
    outer_node.iter = copy.deepcopy(inner_node.iter)
    inner_node.target = outer_target
    inner_node.iter = outer_iter

    ast.fix_missing_locations(tree)
    return ast.unparse(tree)


# ---------------------------------------------------------------------------
# Compare pipeline
# ---------------------------------------------------------------------------

NO_PATTERN_MESSAGE = "No automatic optimization pattern detected for this code"


def optimize_and_compare(original_code: str, cache_config: dict) -> dict:
    """
    Full auto-optimize pipeline:
      1. Detect a known antipattern (currently: loop interchange only).
      2. Generate the transformed code.
      3. Run BOTH versions through the same analyzer + simulator pipeline.
      4. Return a structured before/after comparison with real simulated numbers.

    cache_config keys: cache_size_bytes, block_size_bytes, associativity.

    If no known pattern is detected, returns:
      { "optimization_found": False, "message": NO_PATTERN_MESSAGE }
    """
    candidate = detect_loop_interchange(original_code)
    if candidate is None:
        return {
            "optimization_found": False,
            "message": NO_PATTERN_MESSAGE,
        }

    original_result = analyze_code(original_code, **cache_config)
    optimized_result = analyze_code(candidate.transformed_code, **cache_config)

    original_hr = original_result["cache_stats"]["hit_rate"]
    optimized_hr = optimized_result["cache_stats"]["hit_rate"]

    return {
        "optimization_found": True,
        "transformation_applied": "loop interchange",
        "original_hit_rate": original_hr,
        "optimized_hit_rate": optimized_hr,
        "improvement_percentage_points": round((optimized_hr - original_hr) * 100, 2),
        "original_code": original_code,
        "optimized_code": candidate.transformed_code,
        "detection_details": {
            "outer_loop_var": candidate.outer_var,
            "inner_loop_var": candidate.inner_var,
            "array_name": candidate.array_name,
            "outer_loop_line": candidate.outer_lineno,
            "inner_loop_line": candidate.inner_lineno,
        },
        "original_stats": original_result["cache_stats"],
        "optimized_stats": optimized_result["cache_stats"],
        "original_analysis_mode": original_result["analysis_mode"],
        "optimized_analysis_mode": optimized_result["analysis_mode"],
    }
