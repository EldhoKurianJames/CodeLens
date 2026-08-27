"""
Phase 1 tests — cache simulator + code analyzer.

Cache parameters used throughout (unless overridden):
  cache_size_bytes = 512
  block_size_bytes = 64   → 16 int32 elements per block
  associativity    = 2    → 4 sets total

Hand-calculated expectations
─────────────────────────────
Row-major 64×64 matrix (int32, 4 bytes/element):
  Total accesses = 4096
  Block covers 16 consecutive elements.
  Every 16th access is a cold miss → 256 misses, 3840 hits.
  Expected hit rate ≈ 93.75 %

Column-major 64×64 matrix:
  Consecutive accesses stride 64 elements = 256 bytes = 4 blocks.
  All column-0 accesses (rows 0..63) map to set 0 (block_addr % 4 == 0).
  Set 0 holds only 2 blocks (2-way), so every third access evicts.
  Expected hit rate ≈ 0–3 % (effectively 0).

Sequential 1D, 4096 elements, stride 1:
  Same as row-major → expected ≈ 93.75 %

Strided 1D, stride = 16 (= 1 full block):
  Each access lands in a fresh block → 100 % misses.
  Expected hit rate ≈ 0 %
"""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pytest

from cache_simulator import CacheSimulator
from code_analyzer import (
    CodeValidationError,
    analyze_code,
    extract_static_pattern,
    validate_code,
)

# ---------------------------------------------------------------------------
# Fixtures / helpers
# ---------------------------------------------------------------------------

N = 64
ELEM = 4          # bytes per int32
BLOCK = 64        # bytes per cache block
ELEMS_PER_BLOCK = BLOCK // ELEM  # = 16


def make_sim() -> CacheSimulator:
    return CacheSimulator(cache_size_bytes=512, block_size_bytes=64, associativity=2)


def row_major_addresses(n: int = N) -> list:
    return [(i * n + j) * ELEM for i in range(n) for j in range(n)]


def col_major_addresses(n: int = N) -> list:
    return [(i * n + j) * ELEM for j in range(n) for i in range(n)]


def sequential_1d(length: int = 4096, stride: int = 1) -> list:
    return [i * ELEM for i in range(0, length, stride)]


# ---------------------------------------------------------------------------
# 1. Basic hit / miss tests (hand-calculated)
# ---------------------------------------------------------------------------


class TestCacheBasics:
    def test_single_miss(self):
        sim = make_sim()
        hit = sim.access(0)
        assert not hit
        assert sim.misses == 1
        assert sim.hits == 0

    def test_immediate_repeat_is_hit(self):
        sim = make_sim()
        sim.access(0)
        hit = sim.access(4)    # same block (bytes 0–63)
        assert hit
        assert sim.hits == 1

    def test_different_blocks_are_misses(self):
        sim = make_sim()
        sim.access(0)
        hit = sim.access(64)   # block 1
        assert not hit

    def test_access_log_length(self):
        sim = make_sim()
        for addr in [0, 4, 8, 64, 128]:
            sim.access(addr)
        assert len(sim.access_log) == 5

    def test_reset_clears_everything(self):
        sim = make_sim()
        sim.access(0)
        sim.access(64)
        sim.reset()
        assert sim.hits == 0 and sim.misses == 0 and not sim.access_log
        # First access after reset must be a miss again
        assert not sim.access(0)

    def test_hit_rate_empty(self):
        sim = make_sim()
        assert sim.hit_rate == 0.0

    def test_stats_dict_keys(self):
        sim = make_sim()
        sim.access(0)
        keys = sim.stats().keys()
        for key in ("hits", "misses", "total_accesses", "hit_rate", "miss_rate",
                    "cache_size_bytes", "block_size_bytes", "associativity", "num_sets"):
            assert key in keys


# ---------------------------------------------------------------------------
# 2. LRU eviction test (hand-calculated)
# ---------------------------------------------------------------------------


class TestLRUEviction:
    """
    With 4 sets, 2-way associativity:
    Blocks 0, 4, 8, 12, ... share set 0.
    After loading blocks 0 and 4, block 0 is LRU.
    Accessing block 8 evicts block 0.
    Re-accessing block 0 → miss.
    Accessing block 4 (still in set) → hit.
    """

    def test_lru_eviction_sequence(self):
        sim = make_sim()
        sim.access(0 * 64)    # block 0 → set 0: MISS
        sim.access(4 * 64)    # block 4 → set 0: MISS
        sim.access(0 * 64)    # block 0 still in set → HIT (moves to MRU)
        sim.access(8 * 64)    # block 8 → set 0: MISS, evicts block 4 (LRU now)
        hit = sim.access(4 * 64)  # block 4 was evicted → MISS
        assert not hit

    def test_mru_not_evicted(self):
        sim = make_sim()
        sim.access(0 * 64)    # block 0: MISS
        sim.access(4 * 64)    # block 4: MISS
        sim.access(4 * 64)    # block 4: HIT (now MRU)
        sim.access(8 * 64)    # block 8: MISS, evicts block 0 (LRU)
        hit = sim.access(4 * 64)  # block 4 still present → HIT
        assert hit


# ---------------------------------------------------------------------------
# 3. Row-major vs column-major — the key correctness check
# ---------------------------------------------------------------------------


class TestRowVsColumnMajor:
    """
    Aim: hit-rate difference must be dramatic.
    Target: row-major ≥ 85 %, column-major ≤ 10 %.
    (Hand calculation predicts 93.75 % vs ~0 %.)
    """

    def test_row_major_hit_rate(self):
        sim = make_sim()
        sim.access_many(row_major_addresses())
        hr = sim.hit_rate
        print(f"\n[row-major]    hit_rate={hr:.4%}  hits={sim.hits}  misses={sim.misses}")
        assert hr >= 0.85, f"Row-major hit rate too low: {hr:.4%}"

    def test_col_major_hit_rate(self):
        sim = make_sim()
        sim.access_many(col_major_addresses())
        hr = sim.hit_rate
        print(f"[col-major]    hit_rate={hr:.4%}  hits={sim.hits}  misses={sim.misses}")
        assert hr <= 0.10, f"Column-major hit rate unexpectedly high: {hr:.4%}"

    def test_dramatic_difference(self):
        row_sim = make_sim()
        row_sim.access_many(row_major_addresses())

        col_sim = make_sim()
        col_sim.access_many(col_major_addresses())

        delta = row_sim.hit_rate - col_sim.hit_rate
        print(f"[delta]        row={row_sim.hit_rate:.4%}  col={col_sim.hit_rate:.4%}  delta={delta:.4%}")
        assert delta >= 0.70, f"Hit-rate delta not dramatic enough: {delta:.4%}"

    def test_hand_calculated_row_major(self):
        """
        For a 64×64 matrix: 4096 accesses, 256 cold misses (one per block of 16).
        Expected hit rate = 3840/4096 = 0.9375.
        """
        sim = make_sim()
        sim.access_many(row_major_addresses())
        expected_misses = (N * N) // ELEMS_PER_BLOCK  # = 256
        assert sim.misses == expected_misses, (
            f"Expected {expected_misses} misses, got {sim.misses}"
        )
        assert abs(sim.hit_rate - 0.9375) < 1e-4


# ---------------------------------------------------------------------------
# 4. Strided vs sequential (1D)
# ---------------------------------------------------------------------------


class TestStridedVsSequential:
    def test_sequential_high_hit_rate(self):
        sim = make_sim()
        sim.access_many(sequential_1d(stride=1))
        hr = sim.hit_rate
        print(f"\n[sequential]   hit_rate={hr:.4%}  hits={sim.hits}  misses={sim.misses}")
        assert hr >= 0.85

    def test_stride16_near_zero_hit_rate(self):
        """Stride 16 elements = 64 bytes = exactly 1 block → every access is a miss."""
        sim = make_sim()
        sim.access_many(sequential_1d(stride=ELEMS_PER_BLOCK))
        hr = sim.hit_rate
        print(f"[stride-16]    hit_rate={hr:.4%}  hits={sim.hits}  misses={sim.misses}")
        assert hr == 0.0, f"Expected 0% hits for stride-16, got {hr:.4%}"

    def test_stride_vs_sequential_delta(self):
        seq_sim = make_sim()
        seq_sim.access_many(sequential_1d(stride=1))

        str_sim = make_sim()
        str_sim.access_many(sequential_1d(stride=ELEMS_PER_BLOCK))

        delta = seq_sim.hit_rate - str_sim.hit_rate
        print(f"[delta]        seq={seq_sim.hit_rate:.4%}  strided={str_sim.hit_rate:.4%}  delta={delta:.4%}")
        assert delta >= 0.80


# ---------------------------------------------------------------------------
# 5. Code validator tests
# ---------------------------------------------------------------------------


class TestValidator:
    def test_valid_nested_loop(self):
        code = (
            "N = 64\n"
            "arr = [[0] * N for _ in range(N)]\n"
            "for i in range(N):\n"
            "    for j in range(N):\n"
            "        arr[i][j] = i + j\n"
        )
        validate_code(code)  # must not raise

    def test_rejects_import(self):
        with pytest.raises(CodeValidationError, match="Import"):
            validate_code("import os\nprint(os.getcwd())")

    def test_rejects_from_import(self):
        with pytest.raises(CodeValidationError, match="Import"):
            validate_code("from os import path")

    def test_rejects_open(self):
        with pytest.raises(CodeValidationError, match="Disallowed function call"):
            validate_code("f = open('secret.txt')")

    def test_rejects_eval(self):
        with pytest.raises(CodeValidationError, match="Disallowed function call"):
            validate_code("eval('1+1')")

    def test_rejects_exec(self):
        with pytest.raises(CodeValidationError, match="Disallowed function call"):
            validate_code("exec('x=1')")

    def test_rejects_attribute_access(self):
        with pytest.raises(CodeValidationError, match="Method calls"):
            validate_code("arr = [1, 2, 3]\narr.sort()")

    def test_rejects_unknown_call(self):
        with pytest.raises(CodeValidationError, match="Disallowed function call"):
            validate_code("foo(1, 2)")

    def test_rejects_too_long(self):
        with pytest.raises(CodeValidationError, match="too long"):
            validate_code("x = 1\n" * 300)

    def test_accepts_allowed_builtins(self):
        code = (
            "arr = [0] * 100\n"
            "for i in range(len(arr)):\n"
            "    arr[i] = abs(i - 50)\n"
        )
        validate_code(code)  # must not raise


# ---------------------------------------------------------------------------
# 6. Static pattern extractor tests
# ---------------------------------------------------------------------------


class TestPatternExtractor:
    def test_detects_row_major(self):
        code = (
            "N = 64\n"
            "arr = [[0] * N for _ in range(N)]\n"
            "for i in range(64):\n"
            "    for j in range(64):\n"
            "        arr[i][j] = i + j\n"
        )
        p = extract_static_pattern(code)
        assert p.kind == "nested_2d"
        assert p.outer_access_var == "i"
        assert p.inner_access_var == "j"

    def test_detects_col_major(self):
        code = (
            "N = 64\n"
            "arr = [[0] * N for _ in range(N)]\n"
            "for j in range(64):\n"
            "    for i in range(64):\n"
            "        arr[i][j] = i + j\n"
        )
        p = extract_static_pattern(code)
        assert p.kind == "nested_2d"
        assert p.outer_access_var == "i"  # row index
        assert p.inner_access_var == "j"  # col index
        # outer loop is j (slow) but array access is arr[i][j] — i is row
        # outer_access_var should be i (the row variable)

    def test_detects_flat_sequential(self):
        code = "arr = [0] * 100\nfor i in range(100):\n    arr[i] = i\n"
        p = extract_static_pattern(code)
        assert p.kind == "flat_1d"
        assert p.stride == 1

    def test_detects_strided(self):
        code = "arr = [0] * 512\nfor i in range(0, 512, 16):\n    arr[i] = i\n"
        p = extract_static_pattern(code)
        assert p.kind == "flat_1d"
        assert p.stride == 16


# ---------------------------------------------------------------------------
# 7. Full analyze_code pipeline — integration tests
# ---------------------------------------------------------------------------


class TestAnalyzePipeline:
    CACHE_KWARGS = dict(cache_size_bytes=512, block_size_bytes=64, associativity=2)

    def test_row_major_via_api(self):
        code = (
            "arr = [[0] * 64 for _ in range(64)]\n"
            "for i in range(64):\n"
            "    for j in range(64):\n"
            "        arr[i][j] = i + j\n"
        )
        result = analyze_code(code, **self.CACHE_KWARGS)
        hr = result["cache_stats"]["hit_rate"]
        print(f"\n[analyze row-major] hit_rate={hr:.4%}")
        assert hr >= 0.85
        assert result["metadata"]["access_order"] == "row-major"
        assert result["metadata"]["cache_efficiency"] == "high"

    def test_col_major_via_api(self):
        code = (
            "arr = [[0] * 64 for _ in range(64)]\n"
            "for j in range(64):\n"
            "    for i in range(64):\n"
            "        arr[i][j] = i + j\n"
        )
        result = analyze_code(code, **self.CACHE_KWARGS)
        hr = result["cache_stats"]["hit_rate"]
        print(f"[analyze col-major] hit_rate={hr:.4%}")
        assert hr <= 0.10
        assert result["metadata"]["access_order"] == "column-major"
        assert result["metadata"]["cache_efficiency"] == "low"
        assert len(result["metadata"]["issues"]) > 0

    def test_sequential_via_api(self):
        code = "arr = [0] * 512\nfor i in range(512):\n    arr[i] = i\n"
        result = analyze_code(code, **self.CACHE_KWARGS)
        hr = result["cache_stats"]["hit_rate"]
        print(f"[analyze sequential] hit_rate={hr:.4%}")
        assert hr >= 0.85

    def test_strided_via_api(self):
        code = "arr = [0] * 512\nfor i in range(0, 512, 16):\n    arr[i] = i\n"
        result = analyze_code(code, **self.CACHE_KWARGS)
        hr = result["cache_stats"]["hit_rate"]
        print(f"[analyze stride-16] hit_rate={hr:.4%}")
        assert hr <= 0.05

    def test_invalid_code_raises(self):
        code = "import os\nprint(os.getcwd())"
        with pytest.raises(CodeValidationError):
            analyze_code(code, **self.CACHE_KWARGS)

    def test_result_structure(self):
        code = "arr = [0] * 64\nfor i in range(64):\n    arr[i] = i\n"
        result = analyze_code(code, **self.CACHE_KWARGS)
        for key in ("analysis_mode", "total_addresses_traced", "cache_stats",
                    "access_log", "metadata", "pattern"):
            assert key in result, f"Missing key: {key}"
        for key in ("hit_rate", "miss_rate", "total_accesses", "hits", "misses"):
            assert key in result["cache_stats"]
        for key in ("issues", "suggestions", "summary", "cache_efficiency"):
            assert key in result["metadata"]
