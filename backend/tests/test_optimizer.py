"""
Feature 1 tests — auto-optimizer with re-simulation (code_optimizer.py).

Key case: column-major traversal of a 512x512 matrix. The optimizer must:
  1. detect the loop-interchange antipattern,
  2. generate a row-major version,
  3. prove via re-simulation that the hit rate improves by a meaningful margin
     (expected: ~0% -> ~93.75% with the default 512B/64B/2-way cache).
"""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from code_optimizer import (
    NO_PATTERN_MESSAGE,
    detect_loop_interchange,
    optimize_and_compare,
)

CACHE = dict(cache_size_bytes=512, block_size_bytes=64, associativity=2)

COL_MAJOR_512 = (
    "arr = [[0] * 512 for _ in range(512)]\n"
    "for j in range(512):\n"
    "    for i in range(512):\n"
    "        arr[i][j] = i + j\n"
)

ROW_MAJOR_512 = (
    "arr = [[0] * 512 for _ in range(512)]\n"
    "for i in range(512):\n"
    "    for j in range(512):\n"
    "        arr[i][j] = i + j\n"
)

FLAT_1D = (
    "arr = [0] * 512\n"
    "for i in range(512):\n"
    "    arr[i] = i\n"
)


# ---------------------------------------------------------------------------
# Detection
# ---------------------------------------------------------------------------


class TestDetection:
    def test_detects_col_major_antipattern(self):
        cand = detect_loop_interchange(COL_MAJOR_512)
        assert cand is not None, "Failed to detect the col-major antipattern"
        assert cand.outer_var == "j"
        assert cand.inner_var == "i"
        assert cand.array_name == "arr"

    def test_no_detection_on_row_major(self):
        """Row-major is already optimal — must NOT suggest an interchange."""
        assert detect_loop_interchange(ROW_MAJOR_512) is None

    def test_no_detection_on_flat_1d(self):
        assert detect_loop_interchange(FLAT_1D) is None

    def test_no_detection_on_invalid_syntax(self):
        assert detect_loop_interchange("for i in range(:\n  pass") is None

    def test_alternate_var_names(self):
        """Antipattern with different variable names (outer=col, inner=row)."""
        code = (
            "m = [[0] * 64 for _ in range(64)]\n"
            "for col in range(64):\n"
            "    for row in range(64):\n"
            "        m[row][col] = 1\n"
        )
        cand = detect_loop_interchange(code)
        assert cand is not None
        assert cand.outer_var == "col"
        assert cand.inner_var == "row"

    def test_skips_dependent_inner_bounds(self):
        """Triangular loop: inner bound depends on outer var — interchange unsafe."""
        code = (
            "arr = [[0] * 64 for _ in range(64)]\n"
            "for j in range(64):\n"
            "    for i in range(j):\n"
            "        arr[i][j] = 1\n"
        )
        assert detect_loop_interchange(code) is None


# ---------------------------------------------------------------------------
# Transformation correctness
# ---------------------------------------------------------------------------


class TestTransformation:
    def test_swapped_code_is_row_major(self):
        cand = detect_loop_interchange(COL_MAJOR_512)
        assert cand is not None
        # After interchange the outer loop must be over `i` (the row variable)
        lines = cand.transformed_code.splitlines()
        for_lines = [ln for ln in lines if ln.strip().startswith("for ")]
        assert len(for_lines) == 2
        assert "for i in range(512):" in for_lines[0]
        assert "for j in range(512):" in for_lines[1]

    def test_body_is_unchanged(self):
        cand = detect_loop_interchange(COL_MAJOR_512)
        assert cand is not None
        # The access expression itself must stay identical
        assert "arr[i][j] = i + j" in cand.transformed_code

    def test_transformed_code_is_valid_python(self):
        cand = detect_loop_interchange(COL_MAJOR_512)
        assert cand is not None
        compile(cand.transformed_code, "<optimized>", "exec")  # must not raise


# ---------------------------------------------------------------------------
# Full optimize_and_compare pipeline — the key before/after numbers
# ---------------------------------------------------------------------------


class TestOptimizeAndCompare:
    def test_col_major_512_improves_meaningfully(self):
        result = optimize_and_compare(COL_MAJOR_512, CACHE)

        assert result["optimization_found"] is True
        assert result["transformation_applied"] == "loop interchange"

        orig_hr = result["original_hit_rate"]
        opt_hr = result["optimized_hit_rate"]
        delta_pp = result["improvement_percentage_points"]

        print(
            f"\n[optimize 512x512] original={orig_hr:.4%}  "
            f"optimized={opt_hr:.4%}  improvement={delta_pp:+.2f}pp"
        )

        # Matches previously verified manual numbers:
        #   col-major ~0%, row-major ~93.75%
        assert orig_hr <= 0.10, f"Original col-major hit rate too high: {orig_hr:.4%}"
        assert opt_hr >= 0.85, f"Optimized row-major hit rate too low: {opt_hr:.4%}"
        assert delta_pp >= 30.0, f"Improvement not meaningful: {delta_pp:+.2f}pp"

    def test_result_structure(self):
        result = optimize_and_compare(COL_MAJOR_512, CACHE)
        for key in (
            "optimization_found", "transformation_applied",
            "original_hit_rate", "optimized_hit_rate",
            "improvement_percentage_points",
            "original_code", "optimized_code",
            "original_stats", "optimized_stats",
            "detection_details",
        ):
            assert key in result, f"Missing key: {key}"

    def test_no_pattern_returns_clear_message(self):
        result = optimize_and_compare(ROW_MAJOR_512, CACHE)
        assert result["optimization_found"] is False
        assert result["message"] == NO_PATTERN_MESSAGE

    def test_no_pattern_on_flat_1d(self):
        result = optimize_and_compare(FLAT_1D, CACHE)
        assert result["optimization_found"] is False

    def test_optimized_code_passes_validation(self):
        """The generated code must survive the same AST whitelist as user code."""
        from code_analyzer import validate_code
        result = optimize_and_compare(COL_MAJOR_512, CACHE)
        validate_code(result["optimized_code"])  # must not raise
