"""
CacheLens AI — FastAPI backend (Phase 2 + 3)

Routes:
  GET  /api/health
  POST /api/analyze
  GET  /api/gallery
  GET  /api/gallery/{item_id}
  POST /api/simulate
"""

from __future__ import annotations

import time
from collections import defaultdict
from typing import Any, Optional

from fastapi import FastAPI, HTTPException, Request, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field, field_validator

from cache_simulator import CacheSimulator
from code_analyzer import CodeValidationError, analyze_code
from code_optimizer import optimize_and_compare
from explanation_generator import generate_explanation, generate_optimization_explanation
from gallery import GALLERY

# ---------------------------------------------------------------------------
# App setup
# ---------------------------------------------------------------------------

app = FastAPI(
    title="CacheLens AI",
    description="Cache-miss analysis for Python code snippets.",
    version="0.3.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["GET", "POST", "OPTIONS"],
    allow_headers=["Content-Type", "Authorization"],
)

# ---------------------------------------------------------------------------
# In-memory rate limiter (simple token-bucket per IP)
# ---------------------------------------------------------------------------

_rate_store: dict[str, list[float]] = defaultdict(list)
RATE_LIMIT_REQUESTS = 20    # max requests per window
RATE_LIMIT_WINDOW = 60.0    # seconds

# Separate, tighter limit for AI explanation calls (costs money)
_ai_rate_store: dict[str, list[float]] = defaultdict(list)
AI_RATE_LIMIT_REQUESTS = 15  # max AI calls per window
AI_RATE_LIMIT_WINDOW = 60.0  # seconds


def _check_rate_limit(ip: str) -> None:
    now = time.monotonic()
    window_start = now - RATE_LIMIT_WINDOW
    timestamps = _rate_store[ip]
    _rate_store[ip] = [t for t in timestamps if t > window_start]
    if len(_rate_store[ip]) >= RATE_LIMIT_REQUESTS:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail=(
                f"Rate limit exceeded: max {RATE_LIMIT_REQUESTS} requests "
                f"per {int(RATE_LIMIT_WINDOW)}s."
            ),
        )
    _rate_store[ip].append(now)


def _check_ai_rate_limit(ip: str) -> bool:
    """Returns False (and does NOT raise) if the AI limit is hit — AI is optional."""
    now = time.monotonic()
    window_start = now - AI_RATE_LIMIT_WINDOW
    _ai_rate_store[ip] = [
        t for t in _ai_rate_store[ip] if t > window_start
    ]
    if len(_ai_rate_store[ip]) >= AI_RATE_LIMIT_REQUESTS:
        return False
    _ai_rate_store[ip].append(now)
    return True


# ---------------------------------------------------------------------------
# Request / response schemas
# ---------------------------------------------------------------------------

MAX_CODE_BYTES = 1024


class CacheConfig(BaseModel):
    block_size_bytes: int = Field(
        default=64,
        ge=8,
        le=512,
        description="Size of one cache block (cache line) in bytes.",
    )
    associativity: int = Field(
        default=2,
        ge=1,
        le=16,
        description="N-way set associativity.",
    )
    size_bytes: int = Field(
        default=512,
        ge=64,
        le=65536,
        description="Total cache size in bytes (must be divisible by block_size_bytes * associativity).",
    )

    @field_validator("size_bytes")
    @classmethod
    def divisible(cls, v: int, info: Any) -> int:
        data = info.data
        block = data.get("block_size_bytes", 64)
        assoc = data.get("associativity", 2)
        if v % (block * assoc) != 0:
            raise ValueError(
                f"size_bytes ({v}) must be divisible by "
                f"block_size_bytes ({block}) * associativity ({assoc}) = {block * assoc}."
            )
        return v


class AnalyzeRequest(BaseModel):
    code: str = Field(..., min_length=1, description="Python code to analyze (max 1 KB).")
    cache_config: CacheConfig = Field(default_factory=CacheConfig)
    include_ai_explanation: bool = Field(
        default=True,
        description="If true, call the AI layer for a plain-English explanation.",
    )
    include_debug: bool = Field(
        default=False,
        description="Dev-only: if true, response includes first 50 raw byte addresses generated.",
    )

    @field_validator("code")
    @classmethod
    def check_code_length(cls, v: str) -> str:
        if len(v.encode()) > MAX_CODE_BYTES:
            raise ValueError(
                f"Code too long: {len(v.encode())} bytes (max {MAX_CODE_BYTES})."
            )
        return v


class OptimizeRequest(BaseModel):
    code: str = Field(..., min_length=1, description="Python code to auto-optimize (max 1 KB).")
    cache_config: CacheConfig = Field(default_factory=CacheConfig)
    include_ai_explanation: bool = Field(
        default=False,
        description="If true, generate an AI summary of the before/after comparison.",
    )

    @field_validator("code")
    @classmethod
    def check_code_length(cls, v: str) -> str:
        if len(v.encode()) > MAX_CODE_BYTES:
            raise ValueError(
                f"Code too long: {len(v.encode())} bytes (max {MAX_CODE_BYTES})."
            )
        return v


# ---------------------------------------------------------------------------
# Error handling
# ---------------------------------------------------------------------------

@app.exception_handler(CodeValidationError)
async def validation_error_handler(request: Request, exc: CodeValidationError) -> JSONResponse:
    return JSONResponse(
        status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
        content={"error": "code_validation_failed", "detail": str(exc)},
    )


@app.exception_handler(RuntimeError)
async def runtime_error_handler(request: Request, exc: RuntimeError) -> JSONResponse:
    return JSONResponse(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        content={"error": "execution_failed", "detail": str(exc)},
    )


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@app.get("/api/health", tags=["meta"])
async def health() -> dict:
    import os
    ai_configured = bool(os.environ.get("ANTHROPIC_API_KEY", "").strip())
    return {
        "status": "ok",
        "version": app.version,
        "ai_available": ai_configured,
        "cache_default": {
            "size_bytes": 512,
            "block_size_bytes": 64,
            "associativity": 2,
            "num_sets": 4,
        },
    }


@app.post("/api/analyze", tags=["analysis"])
async def analyze(request: Request, body: AnalyzeRequest) -> dict:
    """
    Analyze a Python code snippet for cache efficiency.

    Steps:
      1. Rate-limit check (general)
      2. AST whitelist validation (returns 422 on failure with a clear message)
      3. Static / dynamic access-trace extraction
      4. CacheSimulator run
      5. Metadata assembly
      6. (Optional) AI explanation via Claude — rate-limited separately
    """
    ip = request.client.host if request.client else "unknown"
    _check_rate_limit(ip)

    cfg = body.cache_config
    num_sets = cfg.size_bytes // (cfg.block_size_bytes * cfg.associativity)
    if num_sets < 1:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Cache configuration results in zero sets. Increase size_bytes or decrease associativity.",
        )

    result = analyze_code(
        code=body.code,
        cache_size_bytes=cfg.size_bytes,
        block_size_bytes=cfg.block_size_bytes,
        associativity=cfg.associativity,
        include_debug=body.include_debug,
    )

    if body.include_ai_explanation:
        if _check_ai_rate_limit(ip):
            result["ai_explanation"] = generate_explanation(result)
        else:
            result["ai_explanation"] = {
                "explanation": "AI explanation rate limit reached. Please wait a moment and try again.",
                "model": None,
                "cached": False,
                "error": True,
            }

    return result


@app.post("/api/optimize", tags=["analysis"])
async def optimize(request: Request, body: OptimizeRequest) -> dict:
    """
    Auto-optimize a Python code snippet and prove the fix via re-simulation.

    Steps:
      1. Rate-limit check
      2. Detect a known cache antipattern (currently: loop interchange)
      3. Generate the transformed code
      4. Run BOTH versions through the analyzer + simulator pipeline
      5. Return structured before/after comparison
      6. (Optional) AI summary of the comparison — fed ONLY the computed numbers
    """
    ip = request.client.host if request.client else "unknown"
    _check_rate_limit(ip)

    cfg = body.cache_config
    num_sets = cfg.size_bytes // (cfg.block_size_bytes * cfg.associativity)
    if num_sets < 1:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Cache configuration results in zero sets. Increase size_bytes or decrease associativity.",
        )

    result = optimize_and_compare(
        original_code=body.code,
        cache_config=dict(
            cache_size_bytes=cfg.size_bytes,
            block_size_bytes=cfg.block_size_bytes,
            associativity=cfg.associativity,
        ),
    )

    if body.include_ai_explanation and result.get("optimization_found"):
        if _check_ai_rate_limit(ip):
            result["ai_explanation"] = generate_optimization_explanation(result)
        else:
            result["ai_explanation"] = {
                "explanation": "AI explanation rate limit reached. Please wait a moment and try again.",
                "model": None,
                "cached": False,
                "error": True,
            }

    return result


@app.get("/api/gallery", tags=["gallery"])
async def get_gallery() -> list:
    """Return all pre-generated algorithm demo entries (without full access logs)."""
    slim: list[dict] = []
    for entry in GALLERY:
        slim_entry = {
            "id": entry["id"],
            "title": entry["title"],
            "description": entry["description"],
            "variants": [
                {
                    "label": v["label"],
                    "code": v["code"],
                    "cache_stats": v["result"]["cache_stats"],
                    "metadata": v["metadata"],
                }
                for v in entry["variants"]
            ],
        }
        slim.append(slim_entry)
    return slim


@app.get("/api/gallery/{item_id}", tags=["gallery"])
async def get_gallery_item(item_id: str) -> dict:
    """Return one gallery entry with full access logs (for heatmap)."""
    for entry in GALLERY:
        if entry["id"] == item_id:
            return entry
    raise HTTPException(
        status_code=status.HTTP_404_NOT_FOUND,
        detail=f"Gallery item '{item_id}' not found. "
               f"Available: {[e['id'] for e in GALLERY]}",
    )


@app.post("/api/simulate", tags=["analysis"])
async def simulate_raw(request: Request, body: dict) -> dict:
    """
    Lower-level endpoint: accept a raw list of addresses and return cache stats.
    Useful for frontend demos without code submission.

    Body: {
      "addresses": [int, ...],
      "cache_config": { ... },
      "include_ai_explanation": bool,   // optional, default false
      "metadata": { ... }               // optional pattern metadata for AI
    }
    """
    ip = request.client.host if request.client else "unknown"
    _check_rate_limit(ip)

    addresses = body.get("addresses", [])
    if not isinstance(addresses, list) or len(addresses) > 50_000:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="'addresses' must be a list of at most 50 000 integers.",
        )

    raw_cfg = body.get("cache_config", {})
    size = int(raw_cfg.get("size_bytes", 512))
    block = int(raw_cfg.get("block_size_bytes", 64))
    assoc = int(raw_cfg.get("associativity", 2))

    if size % (block * assoc) != 0:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="size_bytes must be divisible by block_size_bytes x associativity.",
        )

    sim = CacheSimulator(size, block, assoc)
    for addr in addresses:
        sim.access(int(addr))

    result: dict = {
        "cache_stats": sim.stats(),
        "access_log": sim.access_log_as_dicts(max_records=4096),
    }

    if body.get("include_ai_explanation", False):
        if _check_ai_rate_limit(ip):
            # Merge in any caller-supplied metadata for richer explanation
            explanation_input = {
                "cache_stats": result["cache_stats"],
                "metadata": body.get("metadata", {}),
            }
            result["ai_explanation"] = generate_explanation(explanation_input)
        else:
            result["ai_explanation"] = {
                "explanation": "AI explanation rate limit reached. Please wait a moment.",
                "model": None,
                "cached": False,
                "error": True,
            }

    return result
