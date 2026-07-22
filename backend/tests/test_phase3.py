"""
Phase 3 tests — AI explanation layer.

Tests are split into two groups:
  1. No-key tests  — always run; test fallback behaviour, prompt construction,
     in-memory caching, and rate-limiting without touching the real API.
  2. Live API test — skipped unless ANTHROPIC_API_KEY is set in the environment.
     When the key IS present this test calls the real API and prints the full
     response so you can evaluate explanation quality.
"""

import os
import sys
import hashlib
import json

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pytest

import explanation_generator as eg

# ---------------------------------------------------------------------------
# Sample analysis results used as fixtures
# ---------------------------------------------------------------------------

ROW_MAJOR_RESULT = {
    "analysis_mode": "static",
    "total_addresses_traced": 4096,
    "cache_stats": {
        "hits": 3840,
        "misses": 256,
        "total_accesses": 4096,
        "hit_rate": 0.9375,
        "miss_rate": 0.0625,
        "cache_size_bytes": 512,
        "block_size_bytes": 64,
        "associativity": 2,
        "num_sets": 4,
    },
    "metadata": {
        "pattern_type": "nested_2d_loop",
        "access_order": "row-major",
        "loop_depth": 2,
        "loop_variables": [
            {"name": "i", "start": 0, "stop": 64, "step": 1},
            {"name": "j", "start": 0, "stop": 64, "step": 1},
        ],
        "array_name": "arr",
        "array_dimensions": [64, 64],
        "inner_loop_varies": "columns",
        "locality": "good spatial",
        "cache_efficiency": "high",
        "issues": [],
        "suggestions": [],
        "summary": "2D nested loop over a 64x64 matrix in row-major order.",
    },
    "access_log": [],
}

COL_MAJOR_RESULT = {
    "analysis_mode": "static",
    "total_addresses_traced": 4096,
    "cache_stats": {
        "hits": 0,
        "misses": 4096,
        "total_accesses": 4096,
        "hit_rate": 0.0,
        "miss_rate": 1.0,
        "cache_size_bytes": 512,
        "block_size_bytes": 64,
        "associativity": 2,
        "num_sets": 4,
    },
    "metadata": {
        "pattern_type": "nested_2d_loop",
        "access_order": "column-major",
        "loop_depth": 2,
        "loop_variables": [
            {"name": "j", "start": 0, "stop": 64, "step": 1},
            {"name": "i", "start": 0, "stop": 64, "step": 1},
        ],
        "array_name": "arr",
        "array_dimensions": [64, 64],
        "inner_loop_varies": "rows",
        "locality": "poor spatial",
        "cache_efficiency": "low",
        "issues": [
            "Column-major traversal: the inner loop variable iterates over rows, "
            "causing cache-line evictions on every inner iteration.",
            "Very low cache hit rate (0.0%) — most memory accesses miss the cache.",
        ],
        "suggestions": [
            "Swap the loop order so the inner loop iterates over columns."
        ],
        "summary": "2D nested loop over a 64x64 matrix in column-major order.",
    },
    "access_log": [],
}

STRIDE_RESULT = {
    "analysis_mode": "static",
    "total_addresses_traced": 32,
    "cache_stats": {
        "hits": 0,
        "misses": 32,
        "total_accesses": 32,
        "hit_rate": 0.0,
        "miss_rate": 1.0,
        "cache_size_bytes": 512,
        "block_size_bytes": 64,
        "associativity": 2,
        "num_sets": 4,
    },
    "metadata": {
        "pattern_type": "flat_1d_loop",
        "access_order": "strided",
        "stride": 16,
        "locality": "poor spatial",
        "cache_efficiency": "low",
        "issues": [
            "Stride-16 access pattern: skipping 15 elements on each iteration "
            "reduces spatial locality and increases cache misses."
        ],
        "suggestions": ["Use sequential (stride-1) access where possible."],
        "summary": "1D loop with stride 16 over 'arr'.",
    },
    "access_log": [],
}


# ---------------------------------------------------------------------------
# Helper: temporarily override env var for a test
# ---------------------------------------------------------------------------

class _EnvPatch:
    def __init__(self, key: str, value: str | None):
        self._key = key
        self._value = value
        self._original = os.environ.get(key)

    def __enter__(self):
        if self._value is None:
            os.environ.pop(self._key, None)
        else:
            os.environ[self._key] = self._value
        eg._response_cache.clear()  # clear between tests
        return self

    def __exit__(self, *_):
        if self._original is None:
            os.environ.pop(self._key, None)
        else:
            os.environ[self._key] = self._original
        eg._response_cache.clear()


# ---------------------------------------------------------------------------
# 1. No-key / fallback tests (always run)
# ---------------------------------------------------------------------------


class TestFallback:
    def test_missing_key_returns_fallback(self):
        with _EnvPatch("ANTHROPIC_API_KEY", None):
            result = eg.generate_explanation(ROW_MAJOR_RESULT)
        assert result["error"] is True
        assert "ANTHROPIC_API_KEY" in result["explanation"]
        assert result["model"] is None

    def test_bad_key_returns_fallback_not_raise(self):
        with _EnvPatch("ANTHROPIC_API_KEY", "sk-ant-INVALID-KEY-FOR-TESTING"):
            result = eg.generate_explanation(ROW_MAJOR_RESULT)
        # Must not raise; must contain a graceful message
        assert isinstance(result, dict)
        assert "explanation" in result
        assert result["error"] is True
        # Key must NOT appear in any returned value
        dumped = json.dumps(result)
        assert "INVALID-KEY-FOR-TESTING" not in dumped

    def test_fallback_explanation_is_human_friendly(self):
        with _EnvPatch("ANTHROPIC_API_KEY", "sk-ant-INVALID"):
            result = eg.generate_explanation(ROW_MAJOR_RESULT)
        # Message should be readable, not a raw exception repr
        assert len(result["explanation"]) > 20
        assert "Traceback" not in result["explanation"]
        assert "Exception" not in result["explanation"]


class TestPromptBuilder:
    def test_prompt_contains_hit_rate(self):
        prompt = eg._build_prompt(ROW_MAJOR_RESULT)
        assert "93.8%" in prompt or "93.7%" in prompt

    def test_prompt_contains_array_dims(self):
        prompt = eg._build_prompt(ROW_MAJOR_RESULT)
        assert "64" in prompt

    def test_prompt_contains_cache_config(self):
        prompt = eg._build_prompt(ROW_MAJOR_RESULT)
        assert "512" in prompt   # cache size
        assert "64" in prompt    # block size

    def test_prompt_contains_issues_for_bad_pattern(self):
        prompt = eg._build_prompt(COL_MAJOR_RESULT)
        assert "column" in prompt.lower() or "Column" in prompt

    def test_prompt_requests_improvement_for_low_hit_rate(self):
        prompt = eg._build_prompt(COL_MAJOR_RESULT)
        assert "change" in prompt.lower() or "improve" in prompt.lower()

    def test_prompt_does_not_request_improvement_for_high_hit_rate(self):
        prompt = eg._build_prompt(ROW_MAJOR_RESULT)
        # Should NOT ask for improvement when hit rate is already high
        assert "change" not in prompt.lower() or "improve" not in prompt.lower()

    def test_prompt_never_contains_raw_code(self):
        # Prompt must be built from metadata only, never raw user code
        result_with_code = {**ROW_MAJOR_RESULT, "raw_code": "import os; os.system('rm -rf /')"}
        prompt = eg._build_prompt(result_with_code)
        assert "import os" not in prompt
        assert "rm -rf" not in prompt


class TestInMemoryCache:
    def test_same_input_uses_cache(self):
        eg._response_cache.clear()
        key = eg._cache_key(ROW_MAJOR_RESULT)

        # Pre-populate cache manually (simulates a previous live call)
        cached_entry = {
            "explanation": "Cached explanation text.",
            "model": eg.MODEL,
            "cached": True,
            "error": False,
        }
        eg._response_cache[key] = cached_entry

        result = eg.generate_explanation(ROW_MAJOR_RESULT)
        assert result["cached"] is True
        assert result["explanation"] == "Cached explanation text."

    def test_different_inputs_different_keys(self):
        k1 = eg._cache_key(ROW_MAJOR_RESULT)
        k2 = eg._cache_key(COL_MAJOR_RESULT)
        assert k1 != k2

    def test_cache_key_is_stable(self):
        k1 = eg._cache_key(ROW_MAJOR_RESULT)
        k2 = eg._cache_key(ROW_MAJOR_RESULT)
        assert k1 == k2

    def test_clear_cache(self):
        eg._response_cache["dummy"] = {"explanation": "x"}
        cleared = eg.clear_cache()
        assert cleared >= 1
        assert len(eg._response_cache) == 0


# ---------------------------------------------------------------------------
# 2. Live API test — skipped if no key
# ---------------------------------------------------------------------------

LIVE = pytest.mark.skipif(
    not os.environ.get("ANTHROPIC_API_KEY", "").strip(),
    reason="ANTHROPIC_API_KEY not set — skipping live API test",
)


@LIVE
def test_live_explanation_row_major():
    """
    Calls the real Anthropic API with a row-major result and prints the output.
    Review the text manually to confirm explanation quality.
    """
    eg._response_cache.clear()
    result = eg.generate_explanation(ROW_MAJOR_RESULT)

    print("\n" + "=" * 60)
    print("LIVE AI EXPLANATION — Row-Major 64x64 (93.75% hit rate)")
    print("=" * 60)
    print(result["explanation"])
    print(f"\n[model={result['model']}, cached={result['cached']}, error={result['error']}]")
    print("=" * 60)

    assert result["error"] is False
    assert result["model"] == eg.MODEL
    assert len(result["explanation"]) > 40
    # Sanity: Claude should mention the hit rate or a related concept
    explanation_lower = result["explanation"].lower()
    assert any(
        term in explanation_lower
        for term in ("hit", "cache", "spatial", "line", "block", "93", "row")
    ), f"Explanation seems unrelated to the input:\n{result['explanation']}"


@LIVE
def test_live_explanation_col_major():
    """
    Calls the real Anthropic API with a column-major (0% hit rate) result.
    Checks that Claude mentions the inefficiency and suggests improvement.
    """
    eg._response_cache.clear()
    result = eg.generate_explanation(COL_MAJOR_RESULT)

    print("\n" + "=" * 60)
    print("LIVE AI EXPLANATION — Column-Major 64x64 (0.00% hit rate)")
    print("=" * 60)
    print(result["explanation"])
    print(f"\n[model={result['model']}, cached={result['cached']}, error={result['error']}]")
    print("=" * 60)

    assert result["error"] is False
    explanation_lower = result["explanation"].lower()
    assert any(
        term in explanation_lower
        for term in ("miss", "evict", "column", "row", "loop", "stride", "swap", "order")
    ), f"Explanation doesn't mention inefficiency:\n{result['explanation']}"


@LIVE
def test_live_cache_hit_on_second_call():
    """Second call with identical input must be served from in-memory cache."""
    eg._response_cache.clear()

    first = eg.generate_explanation(STRIDE_RESULT)
    assert first["cached"] is False   # first call hits the API

    second = eg.generate_explanation(STRIDE_RESULT)
    assert second["cached"] is True   # second call served from cache
    assert second["explanation"] == first["explanation"]
