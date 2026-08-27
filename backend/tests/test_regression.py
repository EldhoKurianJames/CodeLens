"""
Regression test suite — guard against silent reintroduction of known bugs.

Test classes
------------
1. TestTinyHandCalc
       4-set direct-mapped cache, a fixed 8-address sequence.
       Every hit/miss outcome and the final counts are hand-calculated and asserted exactly.

2. TestLargeMatrix32KB
       512x512 matrix (1 MB working set) vs 32 KB cache.
       Row-major hit rate must be >= col-major hit rate + 30 percentage points.

3. TestCacheBiggerThanDataset
       Dataset fits entirely inside the cache.
       Hit rate must exceed 95 % regardless of access order.

4. TestStrideEqualsBlock
       Stride == block size => every access lands on a new block => hit rate < 10 %.

5. TestAssociativityEffect
       Same cache size and pattern; fully-associative hit rate >= direct-mapped hit rate.
       Also asserts exact hit/miss counts for the conflict-thrash scenario.

6. TestDynamicPathRegression
       Regression guard for the _reconstruct_2d_addresses bug (fixed 2026-07).
       Variable-bound loops trigger the dynamic path; before the fix both row-major
       and col-major produced sequential addresses and identical ~99.9 % hit rates.
"""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from cache_simulator import CacheSimulator
from code_analyzer import analyze_code, extract_static_pattern

ELEM = 4  # bytes per int32 element


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def make_sim(cache_size: int = 512, block_size: int = 64, assoc: int = 2) -> CacheSimulator:
    return CacheSimulator(
        cache_size_bytes=cache_size,
        block_size_bytes=block_size,
        associativity=assoc,
    )


def matrix_row_major(n: int) -> list:
    return [(i * n + j) * ELEM for i in range(n) for j in range(n)]


def matrix_col_major(n: int) -> list:
    return [(i * n + j) * ELEM for j in range(n) for i in range(n)]


# ---------------------------------------------------------------------------
# 1. Tiny hand-calculated example
# ---------------------------------------------------------------------------
#
# Config: 256-byte cache, 64-byte blocks, 1-way (direct-mapped) -> 4 sets
#
# Addr  Block  Set   Tag   Outcome
# ----  -----  ---   ---   -------
#    0      0    0     0   MISS  (cold)
#   64      1    1     0   MISS  (cold)
#  128      2    2     0   MISS  (cold)
#  192      3    3     0   MISS  (cold)
#    0      0    0     0   HIT   (still resident)
#  256      4    0     1   MISS  (evicts block-0; different tag)
#    0      0    0     0   MISS  (block-0 was just evicted)
#   64      1    1     0   HIT   (block-1 untouched since step 2)
#
# Hits = 2  Misses = 6  Hit-rate = 0.25
# ---------------------------------------------------------------------------


class TestTinyHandCalc:
    ADDRS    = [0, 64, 128, 192, 0, 256, 0, 64]
    EXPECTED = [False, False, False, False, True, False, False, True]

    def _sim(self) -> CacheSimulator:
        return CacheSimulator(cache_size_bytes=256, block_size_bytes=64, associativity=1)

    def test_exact_hit_miss_sequence(self):
        sim = self._sim()
        results = [sim.access(a) for a in self.ADDRS]
        assert results == self.EXPECTED, f"Expected {self.EXPECTED}, got {results}"

    def test_exact_hit_count(self):
        sim = self._sim()
        for a in self.ADDRS:
            sim.access(a)
        assert sim.hits == 2, f"Expected 2 hits, got {sim.hits}"

    def test_exact_miss_count(self):
        sim = self._sim()
        for a in self.ADDRS:
            sim.access(a)
        assert sim.misses == 6, f"Expected 6 misses, got {sim.misses}"

    def test_exact_hit_rate(self):
        sim = self._sim()
        for a in self.ADDRS:
            sim.access(a)
        assert abs(sim.hit_rate - 0.25) < 1e-9, f"Expected 0.25, got {sim.hit_rate}"


# ---------------------------------------------------------------------------
# 2. 512x512 matrix with 32 KB cache
# ---------------------------------------------------------------------------
#
# 32 KB cache: cache_size=32768, block_size=64, assoc=2 -> 256 sets, 512 blocks.
# Working set = 512*512*4 = 1 MB >> 32 KB.
#
# Row-major:  one cold miss per 16-element block -> hit rate ~93.75 %
# Col-major:  stride = 512*4 = 2048 bytes = 32 blocks ->
#             aliasing causes near-total cache thrashing -> hit rate ~0 %
# ---------------------------------------------------------------------------


class TestLargeMatrix32KB:
    CACHE = dict(cache_size=32768, block_size=64, assoc=2)

    def test_row_major_high_hit_rate(self):
        sim = make_sim(**self.CACHE)
        sim.access_many(matrix_row_major(512))
        assert sim.hit_rate >= 0.85, (
            f"Row-major 512x512 hit rate too low: {sim.hit_rate:.4%}"
        )

    def test_col_major_low_hit_rate(self):
        sim = make_sim(**self.CACHE)
        sim.access_many(matrix_col_major(512))
        assert sim.hit_rate <= 0.10, (
            f"Col-major 512x512 hit rate unexpectedly high: {sim.hit_rate:.4%}"
        )

    def test_gap_at_least_30pp(self):
        row_sim = make_sim(**self.CACHE)
        row_sim.access_many(matrix_row_major(512))

        col_sim = make_sim(**self.CACHE)
        col_sim.access_many(matrix_col_major(512))

        gap = row_sim.hit_rate - col_sim.hit_rate
        print(
            f"\n[32KB 512x512] row={row_sim.hit_rate:.4%}  "
            f"col={col_sim.hit_rate:.4%}  gap={gap:.4%}"
        )
        assert gap >= 0.30, (
            f"Row-major vs col-major gap must be >= 30pp, got {gap:.4%}"
        )


# ---------------------------------------------------------------------------
# 3. Cache bigger than dataset — hit rate > 95 %
# ---------------------------------------------------------------------------
#
# 32 elements * 4 bytes = 128 bytes, fits in 2 cache blocks.
# 512-byte cache holds 8 blocks.  After the first cold pass the entire
# dataset is resident; the second pass is all hits.
# Two-pass hit rate = 62/64 = 96.875 % > 95 %.
# ---------------------------------------------------------------------------


class TestCacheBiggerThanDataset:
    def _run_two_passes(self, addrs: list) -> float:
        sim = make_sim(cache_size=512, block_size=64, assoc=2)
        sim.access_many(addrs + addrs)
        return sim.hit_rate

    def test_sequential_warm_cache(self):
        addrs = [i * ELEM for i in range(32)]
        hr = self._run_two_passes(addrs)
        assert hr > 0.95, f"Warm sequential hit rate too low: {hr:.4%}"

    def test_reversed_order_warm_cache(self):
        addrs = [i * ELEM for i in reversed(range(32))]
        hr = self._run_two_passes(addrs)
        assert hr > 0.95, f"Warm reversed hit rate too low: {hr:.4%}"

    def test_col_major_small_matrix_warm_cache(self):
        """
        4x4 matrix = 16 elements = 64 bytes = 1 block.
        Col-major reordering doesn't matter — everything fits.
        Two passes: 1 cold miss + 31 hits = 96.875 % > 95 %.
        """
        addrs = matrix_col_major(4) + matrix_col_major(4)
        sim = make_sim(cache_size=512, block_size=64, assoc=2)
        sim.access_many(addrs)
        assert sim.hit_rate > 0.95, (
            f"Small-matrix col-major warm hit rate too low: {sim.hit_rate:.4%}"
        )


# ---------------------------------------------------------------------------
# 4. Stride equals block size — hit rate < 10 %
# ---------------------------------------------------------------------------
#
# block_size = 64 bytes = 16 int32 elements.
# Jumping by exactly 16 elements each time => landing on a fresh block every
# access => no spatial locality => 0 % hit rate.
# ---------------------------------------------------------------------------


class TestStrideEqualsBlock:
    BLOCK_ELEMS = 64 // ELEM  # 16

    def test_stride_block_near_zero_hits(self):
        addrs = [i * self.BLOCK_ELEMS * ELEM for i in range(256)]
        sim = make_sim()
        sim.access_many(addrs)
        assert sim.hit_rate < 0.10, (
            f"Stride-{self.BLOCK_ELEMS} hit rate should be near zero, got {sim.hit_rate:.4%}"
        )

    def test_stride_block_worse_than_sequential(self):
        sequential = [i * ELEM for i in range(256)]
        strided    = [i * self.BLOCK_ELEMS * ELEM for i in range(256)]

        seq_sim = make_sim()
        seq_sim.access_many(sequential)

        str_sim = make_sim()
        str_sim.access_many(strided)

        gap = seq_sim.hit_rate - str_sim.hit_rate
        assert gap >= 0.80, (
            f"Sequential vs stride-block gap must be >= 80pp, got {gap:.4%}"
        )


# ---------------------------------------------------------------------------
# 5. Direct-mapped vs fully-associative
# ---------------------------------------------------------------------------
#
# 256-byte cache, 64-byte blocks.
# Direct-mapped  -> 4 sets, 1 slot each.
# Fully-assoc    -> 1 set, 4 slots.
#
# Conflict pattern: three blocks that all alias to set-0 in direct-mapped
#   (block 0 @ addr=0, block 4 @ addr=256, block 8 @ addr=512)
# Repeated: 0->256->512->0->256->512
#
# Direct-mapped: every access evicts the previous occupant -> 0 hits (thrashing).
# Fully-assoc:   all 3 blocks fit in the single 4-slot set -> 3 hits on second pass.
# ---------------------------------------------------------------------------


class TestAssociativityEffect:
    CACHE_SIZE   = 256
    BLOCK_SIZE   = 64
    CONFLICT_SEQ = [0, 256, 512, 0, 256, 512]

    def test_fully_associative_ge_direct_mapped(self):
        direct = CacheSimulator(
            cache_size_bytes=self.CACHE_SIZE,
            block_size_bytes=self.BLOCK_SIZE,
            associativity=1,
        )
        direct.access_many(self.CONFLICT_SEQ)

        full = CacheSimulator(
            cache_size_bytes=self.CACHE_SIZE,
            block_size_bytes=self.BLOCK_SIZE,
            associativity=4,
        )
        full.access_many(self.CONFLICT_SEQ)

        assert full.hit_rate >= direct.hit_rate, (
            f"Fully-associative ({full.hit_rate:.4%}) must be >= "
            f"direct-mapped ({direct.hit_rate:.4%})"
        )

    def test_direct_mapped_conflict_thrash_zero_hits(self):
        """
        Blocks 0, 4, 8 all map to set-0 in a 4-set direct-mapped cache.
        Every access evicts the previous one -> 0 hits.
        """
        direct = CacheSimulator(
            cache_size_bytes=self.CACHE_SIZE,
            block_size_bytes=self.BLOCK_SIZE,
            associativity=1,
        )
        direct.access_many(self.CONFLICT_SEQ)
        assert direct.hits == 0, (
            f"Direct-mapped conflict thrash: expected 0 hits, got {direct.hits}"
        )

    def test_fully_associative_no_thrash_three_hits(self):
        """
        4-slot set can hold all 3 blocks simultaneously.
        Second visit to each block -> 3 hits.
        """
        full = CacheSimulator(
            cache_size_bytes=self.CACHE_SIZE,
            block_size_bytes=self.BLOCK_SIZE,
            associativity=4,
        )
        full.access_many(self.CONFLICT_SEQ)
        assert full.hits == 3, (
            f"Fully-associative: expected 3 hits, got {full.hits}"
        )


# ---------------------------------------------------------------------------
# 6. Regression: dynamic path (variable bounds) row-major vs col-major
# ---------------------------------------------------------------------------
#
# Bug (fixed 2026-07): _reconstruct_2d_addresses compared small loop indices
# (0..N-1) against large Python object-ID memory addresses in `known_ids`,
# which never matched.  The fallback returned the outer array's row-index list
# treated as column data -> sequential addresses for BOTH traversal orders ->
# identical ~99.9 % hit rates.
#
# Fix: consecutive-pair heuristic.  For arr[i][j], the outer-array "get" is
# ALWAYS the immediately preceding log entry before the inner-array "set".
# Scan pairs to build inner_obj_id->row mapping, then flat = row*cols + col.
#
# N=32 is used here (small enough for sandbox to complete quickly).
# ---------------------------------------------------------------------------


class TestDynamicPathRegression:
    CACHE = dict(cache_size_bytes=512, block_size_bytes=64, associativity=2)
    N = 32

    _ROW = (
        f"N = {N}\n"
        "arr = [[0]*N for _ in range(N)]\n"
        "for i in range(N):\n"
        "    for j in range(N):\n"
        "        arr[i][j] = i + j\n"
    )

    _COL = (
        f"N = {N}\n"
        "arr = [[0]*N for _ in range(N)]\n"
        "for i in range(N):\n"
        "    for j in range(N):\n"
        "        arr[j][i] = i + j\n"
    )

    def test_both_use_dynamic_path(self):
        """Pre-condition: variable bounds must actually trigger the dynamic path."""
        assert extract_static_pattern(self._ROW).kind == "complex", (
            "Row-major variable code should use the dynamic path (kind='complex')"
        )
        assert extract_static_pattern(self._COL).kind == "complex", (
            "Col-major variable code should use the dynamic path (kind='complex')"
        )

    def test_dynamic_row_major_high_hit_rate(self):
        result = analyze_code(self._ROW, **self.CACHE)
        hr = result["cache_stats"]["hit_rate"]
        assert result["analysis_mode"] == "dynamic"
        assert hr >= 0.85, (
            f"Dynamic row-major hit rate too low: {hr:.4%}. "
            f"Possible regression in _reconstruct_2d_addresses."
        )

    def test_dynamic_col_major_low_hit_rate(self):
        result = analyze_code(self._COL, **self.CACHE)
        hr = result["cache_stats"]["hit_rate"]
        assert result["analysis_mode"] == "dynamic"
        assert hr <= 0.10, (
            f"Dynamic col-major hit rate too high: {hr:.4%}. "
            f"Possible regression in _reconstruct_2d_addresses."
        )

    def test_dynamic_gap_at_least_30pp(self):
        row_hr = analyze_code(self._ROW, **self.CACHE)["cache_stats"]["hit_rate"]
        col_hr = analyze_code(self._COL, **self.CACHE)["cache_stats"]["hit_rate"]
        gap = row_hr - col_hr
        print(f"\n[dynamic N={self.N}] row={row_hr:.4%}  col={col_hr:.4%}  gap={gap:.4%}")
        assert gap >= 0.30, (
            f"Dynamic path gap must be >= 30pp, got {gap:.4%}. "
            f"This is the exact signature of the _reconstruct_2d_addresses bug."
        )

    def test_debug_first_address_row_major(self):
        """arr[0][0] = byte 0; arr[0][1] = byte 4 (sequential stride)."""
        result = analyze_code(self._ROW, **self.CACHE, include_debug=True)
        addrs = result["debug_info"]["first_50_addresses"]
        assert addrs[0] == 0, f"First address should be 0, got {addrs[0]}"
        assert addrs[1] == ELEM, (
            f"Second address (arr[0][1]) should be {ELEM}, got {addrs[1]}"
        )

    def test_debug_first_address_col_major(self):
        """arr[0][0] = byte 0; arr[1][0] = byte N*ELEM (column stride)."""
        result = analyze_code(self._COL, **self.CACHE, include_debug=True)
        addrs = result["debug_info"]["first_50_addresses"]
        col_stride = self.N * ELEM  # 32 * 4 = 128 bytes
        assert addrs[0] == 0, f"First address should be 0, got {addrs[0]}"
        assert addrs[1] == col_stride, (
            f"Second address (arr[1][0]) should be {col_stride}, got {addrs[1]}. "
            f"Col-major stride is wrong — possible regression."
        )
