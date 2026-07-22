"""
explanation_generator.py — Phase 3 AI layer.

Calls Claude to explain pre-computed cache-simulation results in plain English.

Key design constraints (from spec):
  - Only explain given numbers; never invent statistics or write code.
  - max_tokens=300 — keeps responses short and cost minimal.
  - In-memory cache keyed by SHA-256 of input — avoids duplicate API calls.
  - Graceful fallback on any API error — the tool stays usable without AI.
  - API key loaded exclusively from the environment; never logged or surfaced.
"""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
from typing import Optional

from dotenv import load_dotenv


def _load_env() -> None:
    """
    Load .env from the same directory as this file.
    Tries multiple encodings to handle files written by PowerShell (UTF-16 LE
    with BOM) as well as standard UTF-8 files.
    """
    env_path = Path(__file__).parent / ".env"
    for enc in ("utf-8-sig", "utf-16", "utf-8"):
        try:
            load_dotenv(dotenv_path=env_path, encoding=enc, override=False)
            return
        except (UnicodeDecodeError, LookupError):
            continue


_load_env()

# ---------------------------------------------------------------------------
# Optional anthropic import — backend works without the package installed
# ---------------------------------------------------------------------------

try:
    import anthropic as _anthropic

    _ANTHROPIC_AVAILABLE = True
except ImportError:
    _ANTHROPIC_AVAILABLE = False

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

MODEL = "claude-haiku-4-5-20251001"
MAX_TOKENS = 300

SYSTEM_PROMPT = (
    "You are analyzing pre-computed cache simulation results. "
    "Only explain and interpret the given numbers. "
    "Do not invent statistics not present in the input. "
    "Do not write or rewrite code — describe any change in plain English only."
)

_FALLBACK = (
    "AI explanation temporarily unavailable — here are the raw simulation results."
)

# ---------------------------------------------------------------------------
# In-memory response cache
# ---------------------------------------------------------------------------

_response_cache: dict[str, dict] = {}


def _cache_key(analysis_result: dict) -> str:
    """Stable SHA-256 of the JSON-serialised input (sort_keys for stability)."""
    payload = json.dumps(analysis_result, sort_keys=True, default=str)
    return hashlib.sha256(payload.encode()).hexdigest()


# ---------------------------------------------------------------------------
# Prompt builder
# ---------------------------------------------------------------------------


def _build_prompt(result: dict) -> str:
    """
    Construct a compact, structured prompt from the analysis_result dict
    produced by code_analyzer.analyze_code() or the gallery.
    Raw user code is never included.
    """
    cs = result.get("cache_stats", {})
    meta = result.get("metadata", {})

    hit_rate: float = cs.get("hit_rate", 0.0)
    miss_rate: float = cs.get("miss_rate", 0.0)
    total: int = cs.get("total_accesses", 0)
    hits: int = cs.get("hits", 0)
    misses: int = cs.get("misses", 0)

    cache_size: int = cs.get("cache_size_bytes", 512)
    block_size: int = cs.get("block_size_bytes", 64)
    assoc: int = cs.get("associativity", 2)
    num_sets: int = cs.get("num_sets", 4)
    elems_per_block = block_size // 4  # simulated int32 elements

    pattern_type: str = meta.get("pattern_type", "unknown")
    access_order: str = meta.get("access_order", "unknown")
    array_dims: list = meta.get("array_dimensions", [])
    stride = meta.get("stride", 1)
    issues: list[str] = meta.get("issues", [])
    suggestions: list[str] = meta.get("suggestions", [])
    summary: str = meta.get("summary", "")

    lines: list[str] = [
        "Cache simulation results:",
        "",
        f"Pattern: {pattern_type}  |  Access order: {access_order}",
    ]

    if summary:
        lines.append(f"Summary: {summary}")
    if array_dims:
        dims_str = " x ".join(str(d) for d in array_dims)
        lines.append(f"Array dimensions: {dims_str}  (int32, 4 bytes/element)")
    if stride and stride != 1:
        lines.append(f"Access stride: {stride} elements between accesses")

    lines += [
        f"Total memory accesses traced: {total:,}",
        "",
        "Cache hardware model:",
        f"  Total size : {cache_size} bytes",
        f"  Block size : {block_size} bytes  ({elems_per_block} int32 elements per cache line)",
        f"  Associativity: {assoc}-way LRU  |  {num_sets} sets",
        "",
        "Simulation output:",
        f"  Hit rate  : {hit_rate:.1%}  ({hits:,} hits)",
        f"  Miss rate : {miss_rate:.1%}  ({misses:,} misses)",
    ]

    if issues:
        lines.append("")
        lines.append("Detected cache-efficiency issues:")
        for issue in issues:
            lines.append(f"  - {issue}")

    if suggestions:
        lines.append("")
        lines.append("Suggested optimizations:")
        for s in suggestions:
            lines.append(f"  - {s}")

    lines += [
        "",
        "Your task:",
        "1. In 2-3 sentences explain WHY this specific access pattern produces"
        f" this hit rate ({hit_rate:.1%}), referencing the actual numbers above.",
    ]

    if hit_rate < 0.70:
        lines.append(
            "2. Describe in one sentence the ONE concrete change that would most"
            " improve the hit rate. Do NOT write any code — plain English only."
        )

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def generate_explanation(analysis_result: dict) -> dict:
    """
    Generate a plain-English AI explanation of the cache simulation result.

    Returns:
        {
          "explanation": str,      # 2-3 sentences from Claude
          "model": str,            # model name used
          "cached": bool,          # True if served from in-memory cache
          "error": bool,           # True only on API failure
        }

    On any failure (missing key, rate-limit, network) returns a fallback dict
    with error=True and a human-friendly message — never raises.
    """
    # Check cache first — valid regardless of whether key is currently set
    key = _cache_key(analysis_result)
    if key in _response_cache:
        return _response_cache[key]

    if not _ANTHROPIC_AVAILABLE:
        return {
            "explanation": (
                "AI explanation unavailable: the 'anthropic' package is not installed. "
                "Run: pip install anthropic"
            ),
            "model": None,
            "cached": False,
            "error": True,
        }

    api_key = os.environ.get("ANTHROPIC_API_KEY", "").strip()
    if not api_key:
        return {
            "explanation": (
                "AI explanation unavailable: ANTHROPIC_API_KEY environment variable is not set. "
                + _FALLBACK
            ),
            "model": None,
            "cached": False,
            "error": True,
        }

    prompt = _build_prompt(analysis_result)

    try:
        client = _anthropic.Anthropic(api_key=api_key)
        message = client.messages.create(
            model=MODEL,
            max_tokens=MAX_TOKENS,
            system=SYSTEM_PROMPT,
            messages=[{"role": "user", "content": prompt}],
        )
        text: str = message.content[0].text.strip()

        result: dict = {
            "explanation": text,
            "model": MODEL,
            "cached": False,
            "error": False,
        }
        # Store in cache with cached=True for future hits
        _response_cache[key] = {**result, "cached": True}
        return result

    except Exception as exc:
        # Deliberately generic — never surface the API key or internal tokens
        error_type = type(exc).__name__
        return {
            "explanation": _FALLBACK,
            "model": MODEL,
            "cached": False,
            "error": True,
            "error_type": error_type,
        }


def _build_optimization_prompt(comparison: dict) -> str:
    """
    Prompt for before/after optimization results.
    Feeds ONLY the structured numeric comparison — never raw user code.
    """
    orig_hr = comparison.get("original_hit_rate", 0.0)
    opt_hr = comparison.get("optimized_hit_rate", 0.0)
    delta_pp = comparison.get("improvement_percentage_points", 0.0)
    transform = comparison.get("transformation_applied", "unknown")
    orig_stats = comparison.get("original_stats", {})
    opt_stats = comparison.get("optimized_stats", {})

    lines = [
        "An automatic code optimization was applied and BOTH versions were",
        "re-simulated through the same cache simulator. Results:",
        "",
        f"Transformation applied: {transform}",
        "",
        "BEFORE (original code):",
        f"  Hit rate : {orig_hr:.1%}",
        f"  Hits     : {orig_stats.get('hits', 0):,}",
        f"  Misses   : {orig_stats.get('misses', 0):,}",
        "",
        "AFTER (optimized code):",
        f"  Hit rate : {opt_hr:.1%}",
        f"  Hits     : {opt_stats.get('hits', 0):,}",
        f"  Misses   : {opt_stats.get('misses', 0):,}",
        "",
        f"Measured improvement: {delta_pp:+.2f} percentage points",
        "",
        "Cache hardware model:",
        f"  Total size   : {orig_stats.get('cache_size_bytes', 512)} bytes",
        f"  Block size   : {orig_stats.get('block_size_bytes', 64)} bytes",
        f"  Associativity: {orig_stats.get('associativity', 2)}-way LRU",
        "",
        "Your task: in 2-3 sentences, explain what this transformation changed",
        "about the memory access pattern and WHY it produced this specific",
        "hit-rate improvement, referencing only the numbers above.",
        "Do NOT write any code.",
    ]
    return "\n".join(lines)


def generate_optimization_explanation(comparison: dict) -> dict:
    """
    AI explanation of a before/after optimization comparison from
    code_optimizer.optimize_and_compare(). Same guarantees as
    generate_explanation(): cached, graceful fallback, never raises.
    """
    # Key on numeric fields only for cache stability
    cache_input = {
        k: comparison.get(k)
        for k in (
            "transformation_applied",
            "original_hit_rate",
            "optimized_hit_rate",
            "improvement_percentage_points",
        )
    }
    key = _cache_key(cache_input)
    if key in _response_cache:
        return _response_cache[key]

    if not _ANTHROPIC_AVAILABLE:
        return {
            "explanation": (
                "AI explanation unavailable: the 'anthropic' package is not installed."
            ),
            "model": None,
            "cached": False,
            "error": True,
        }

    api_key = os.environ.get("ANTHROPIC_API_KEY", "").strip()
    if not api_key:
        return {
            "explanation": "AI explanation unavailable: ANTHROPIC_API_KEY is not set. " + _FALLBACK,
            "model": None,
            "cached": False,
            "error": True,
        }

    prompt = _build_optimization_prompt(comparison)

    try:
        client = _anthropic.Anthropic(api_key=api_key)
        message = client.messages.create(
            model=MODEL,
            max_tokens=MAX_TOKENS,
            system=SYSTEM_PROMPT,
            messages=[{"role": "user", "content": prompt}],
        )
        text: str = message.content[0].text.strip()
        result: dict = {
            "explanation": text,
            "model": MODEL,
            "cached": False,
            "error": False,
        }
        _response_cache[key] = {**result, "cached": True}
        return result
    except Exception as exc:
        return {
            "explanation": _FALLBACK,
            "model": MODEL,
            "cached": False,
            "error": True,
            "error_type": type(exc).__name__,
        }


def clear_cache() -> int:
    """Flush in-memory response cache. Returns number of entries cleared."""
    count = len(_response_cache)
    _response_cache.clear()
    return count
