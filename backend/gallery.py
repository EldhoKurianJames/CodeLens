"""
gallery.py — Pre-generated algorithm demo traces.

Each entry contains:
  - title / description
  - two variants (A vs B) with their Python code snippets and pre-computed
    access traces (so the demo works instantly without running user code)
  - the structural metadata that Phase 3 will send to the LLM

All traces are generated once (at import time) using the CacheSimulator
directly, so there is no subprocess involved.
"""

from __future__ import annotations

from cache_simulator import CacheSimulator

ELEMENT_SIZE = 4      # int32
N = 64                # matrix side length
ARR_LEN = 4096        # 1D array length for sequential/strided demos
CACHE_SIZE = 512
BLOCK_SIZE = 64
ASSOC = 2


def _sim(addresses: list[int]) -> dict:
    sim = CacheSimulator(CACHE_SIZE, BLOCK_SIZE, ASSOC)
    sim.access_many(addresses)
    s = sim.stats()
    return {
        "cache_stats": s,
        "access_log": sim.access_log_as_dicts(max_records=4096),
    }


def _row_major_trace() -> list[int]:
    return [
        (i * N + j) * ELEMENT_SIZE
        for i in range(N)
        for j in range(N)
    ]


def _col_major_trace() -> list[int]:
    return [
        (i * N + j) * ELEMENT_SIZE
        for j in range(N)
        for i in range(N)
    ]


def _sequential_trace(length: int = ARR_LEN, stride: int = 1) -> list[int]:
    return [i * ELEMENT_SIZE for i in range(0, length, stride)]


def _linear_search_trace(length: int = ARR_LEN) -> list[int]:
    return [i * ELEMENT_SIZE for i in range(length // 2)]


def _binary_search_trace(length: int = ARR_LEN) -> list[int]:
    """Simulate binary search access indices on a sorted array of `length`."""
    accesses: list[int] = []
    lo, hi = 0, length - 1
    while lo <= hi:
        mid = (lo + hi) // 2
        accesses.append(mid * ELEMENT_SIZE)
        hi = mid - 1  # always go left — worst-case scattered accesses
    return accesses


def _fibonacci_memo_trace(n: int = 40) -> list[int]:
    """Memoized fibonacci — sequential reads of dp[0..k]."""
    return [i * ELEMENT_SIZE for i in range(n)]


def _fibonacci_naive_trace(n: int = 35) -> list[int]:
    """
    Naive recursive fibonacci.  Access pattern approximated as the
    sequence of dp indices visited in a DFS call tree.
    """
    indices: list[int] = []

    def _fib(k: int) -> None:
        if k <= 1:
            indices.append(k)
            return
        indices.append(k)
        _fib(k - 1)
        _fib(k - 2)

    _fib(n)
    return [i * ELEMENT_SIZE for i in indices]


# ---------------------------------------------------------------------------
# Gallery entries
# ---------------------------------------------------------------------------

def build_gallery() -> list[dict]:
    row = _sim(_row_major_trace())
    col = _sim(_col_major_trace())
    seq = _sim(_sequential_trace())
    stride8 = _sim(_sequential_trace(stride=16))
    lsearch = _sim(_linear_search_trace())
    bsearch = _sim(_binary_search_trace())
    fib_memo = _sim(_fibonacci_memo_trace())
    fib_naive = _sim(_fibonacci_naive_trace())

    return [
        {
            "id": "matrix_traversal",
            "title": "Matrix Traversal: Row-Major vs Column-Major",
            "description": (
                "A 64×64 integer matrix traversed in row-major order (inner loop "
                "over columns) versus column-major order (inner loop over rows). "
                "Row-major exploits spatial locality — each cache line loads 16 "
                "consecutive elements. Column-major strides across rows, causing "
                "a cache-line eviction on nearly every access."
            ),
            "variants": [
                {
                    "label": "Row-Major (arr[i][j])",
                    "code": (
                        "N = 64\n"
                        "arr = [[0] * N for _ in range(N)]\n"
                        "for i in range(N):\n"
                        "    for j in range(N):\n"
                        "        arr[i][j] = i + j"
                    ),
                    "result": row,
                    "metadata": {
                        "pattern_type": "nested_2d_loop",
                        "access_order": "row-major",
                        "loop_depth": 2,
                        "inner_loop_varies": "columns",
                        "locality": "good spatial",
                        "cache_efficiency": "high",
                        "issues": [],
                        "suggestions": [],
                        "summary": "2D nested loop over a 64×64 matrix in row-major order.",
                    },
                },
                {
                    "label": "Column-Major (arr[j][i])",
                    "code": (
                        "N = 64\n"
                        "arr = [[0] * N for _ in range(N)]\n"
                        "for j in range(N):\n"
                        "    for i in range(N):\n"
                        "        arr[i][j] = i + j"
                    ),
                    "result": col,
                    "metadata": {
                        "pattern_type": "nested_2d_loop",
                        "access_order": "column-major",
                        "loop_depth": 2,
                        "inner_loop_varies": "rows",
                        "locality": "poor spatial",
                        "cache_efficiency": "low",
                        "issues": [
                            "Column-major traversal: the inner loop variable iterates "
                            "over rows, causing cache-line evictions on every inner iteration."
                        ],
                        "suggestions": [
                            "Swap the loop order so the inner loop iterates over columns."
                        ],
                        "summary": "2D nested loop over a 64×64 matrix in column-major order.",
                    },
                },
            ],
        },
        {
            "id": "sequential_vs_strided",
            "title": "Sequential vs Stride-16 Array Access",
            "description": (
                "A 4096-element array accessed sequentially (stride 1) versus "
                "with a stride of 16 elements (64 bytes — exactly one cache line). "
                "Stride-16 jumps to a fresh cache line on every access, achieving "
                "a miss rate close to 100%."
            ),
            "variants": [
                {
                    "label": "Sequential (stride 1)",
                    "code": (
                        "arr = [0] * 4096\n"
                        "for i in range(4096):\n"
                        "    arr[i] = i"
                    ),
                    "result": seq,
                    "metadata": {
                        "pattern_type": "flat_1d_loop",
                        "access_order": "sequential",
                        "stride": 1,
                        "locality": "good spatial",
                        "cache_efficiency": "high",
                        "issues": [],
                        "suggestions": [],
                        "summary": "1D loop with stride 1 over 'arr'.",
                    },
                },
                {
                    "label": "Stride-16 (jumps one cache line)",
                    "code": (
                        "arr = [0] * 4096\n"
                        "for i in range(0, 4096, 16):\n"
                        "    arr[i] = i"
                    ),
                    "result": stride8,
                    "metadata": {
                        "pattern_type": "flat_1d_loop",
                        "access_order": "strided",
                        "stride": 16,
                        "locality": "poor spatial",
                        "cache_efficiency": "low",
                        "issues": [
                            "Stride-16 access pattern: skipping 15 elements on each "
                            "iteration reduces spatial locality and increases cache misses."
                        ],
                        "suggestions": [
                            "Use sequential (stride-1) access where possible."
                        ],
                        "summary": "1D loop with stride 16 over 'arr'.",
                    },
                },
            ],
        },
        {
            "id": "search_algorithms",
            "title": "Linear Search vs Binary Search",
            "description": (
                "Linear search scans a sorted array sequentially — excellent spatial "
                "locality, high hit rate. Binary search jumps to the midpoint on each "
                "step — O(log N) accesses but scattered across the array, each likely "
                "in a different cache line."
            ),
            "variants": [
                {
                    "label": "Linear Search",
                    "code": (
                        "arr = list(range(4096))\n"
                        "target = 2047\n"
                        "for i in range(len(arr)):\n"
                        "    if arr[i] == target:\n"
                        "        break"
                    ),
                    "result": lsearch,
                    "metadata": {
                        "pattern_type": "flat_1d_loop",
                        "access_order": "sequential",
                        "stride": 1,
                        "locality": "good spatial",
                        "cache_efficiency": "high",
                        "issues": [],
                        "suggestions": [],
                        "summary": "Linear scan through sorted array.",
                    },
                },
                {
                    "label": "Binary Search",
                    "code": (
                        "arr = list(range(4096))\n"
                        "target = 0\n"
                        "lo, hi = 0, len(arr) - 1\n"
                        "while lo <= hi:\n"
                        "    mid = (lo + hi) // 2\n"
                        "    if arr[mid] == target:\n"
                        "        break\n"
                        "    elif arr[mid] < target:\n"
                        "        lo = mid + 1\n"
                        "    else:\n"
                        "        hi = mid - 1"
                    ),
                    "result": bsearch,
                    "metadata": {
                        "pattern_type": "binary_search",
                        "access_order": "logarithmic_jumps",
                        "stride": "variable",
                        "locality": "poor spatial",
                        "cache_efficiency": "low",
                        "issues": [
                            "Binary search accesses widely-separated memory locations, "
                            "one per cache line, with almost no reuse between iterations."
                        ],
                        "suggestions": [
                            "For small arrays, linear search may be faster due to better "
                            "cache behavior. For very large arrays, B-tree layouts improve locality."
                        ],
                        "summary": "Binary search on sorted array — scattered, non-sequential accesses.",
                    },
                },
            ],
        },
        {
            "id": "fibonacci",
            "title": "Memoized vs Naive Recursive Fibonacci",
            "description": (
                "Memoized Fibonacci fills a dp table sequentially (arr[0], arr[1], …) — "
                "perfectly sequential, high cache hit rate. Naive recursive Fibonacci "
                "re-computes sub-problems exponentially, revisiting the same indices "
                "in a deep-first call tree with frequent non-sequential jumps."
            ),
            "variants": [
                {
                    "label": "Memoized (dp table)",
                    "code": (
                        "dp = [0] * 40\n"
                        "dp[0] = 0\n"
                        "dp[1] = 1\n"
                        "for i in range(2, 40):\n"
                        "    dp[i] = dp[i-1] + dp[i-2]"
                    ),
                    "result": fib_memo,
                    "metadata": {
                        "pattern_type": "flat_1d_loop",
                        "access_order": "sequential",
                        "stride": 1,
                        "locality": "good spatial and temporal",
                        "cache_efficiency": "high",
                        "issues": [],
                        "suggestions": [],
                        "summary": "Memoized Fibonacci via sequential dp table fill.",
                    },
                },
                {
                    "label": "Naive Recursive (simulated trace)",
                    "code": (
                        "# Naive recursive fibonacci — exponential calls\n"
                        "def fib(n):\n"
                        "    if n <= 1:\n"
                        "        return n\n"
                        "    return fib(n-1) + fib(n-2)"
                    ),
                    "result": fib_naive,
                    "metadata": {
                        "pattern_type": "recursive_calls",
                        "access_order": "depth_first_scattered",
                        "stride": "variable",
                        "locality": "poor temporal",
                        "cache_efficiency": "low",
                        "issues": [
                            "Naive recursive Fibonacci recomputes the same sub-problems "
                            "exponentially, causing repeated non-sequential memory accesses "
                            "and poor cache utilization."
                        ],
                        "suggestions": [
                            "Use memoization (top-down DP) or iterative bottom-up DP "
                            "to achieve O(n) time with sequential memory access."
                        ],
                        "summary": "Naive recursive Fibonacci — exponential recomputation with poor locality.",
                    },
                },
            ],
        },
    ]


GALLERY: list[dict] = build_gallery()
