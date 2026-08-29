"""
CacheLens AI — FastAPI backend (Phase 2 + 3 + security/perf hardening pass)

Routes:
  GET  /api/health              — unauthenticated; `ai_available` only shown to trusted callers
  GET  /api/v1/health           — alias of the above
  POST /api/v1/analyze
  POST /api/v1/optimize
  GET  /api/v1/gallery
  GET  /api/v1/gallery/{item_id}
  POST /api/v1/simulate

All /api/v1/* routes require a valid `X-API-Key` header (checked against the
`API_KEY` environment variable) via the `require_api_key` dependency. If
`API_KEY` is not configured, auth is left OPEN for local/dev convenience and
a startup warning is logged — set `API_KEY` before deploying publicly.
"""

from __future__ import annotations

import copy
import hashlib
import json
import logging
import os
import time
from typing import Any

from cachetools import TTLCache
from fastapi import APIRouter, Depends, FastAPI, Header, HTTPException, Request, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field, field_validator, model_validator
from starlette.middleware.base import BaseHTTPMiddleware

from cache_simulator import CacheSimulator
from code_analyzer import CodeValidationError, analyze_code
from code_optimizer import optimize_and_compare
from explanation_generator import generate_explanation, generate_optimization_explanation
from gallery import GALLERY

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("cachelens")

# ---------------------------------------------------------------------------
# App setup
# ---------------------------------------------------------------------------

app = FastAPI(
    title="CacheLens AI",
    description="Cache-miss analysis for Python code snippets.",
    version="0.4.0",
)

# ---------------------------------------------------------------------------
# CORS — restricted to a real origin allow-list (comma-separated env var)
# ---------------------------------------------------------------------------

_allowed_origins_env = os.environ.get("ALLOWED_ORIGINS", "http://localhost:5173").strip()
ALLOWED_ORIGINS = [o.strip() for o in _allowed_origins_env.split(",") if o.strip()]

# Optional regex for origins that can't be listed as exact strings — e.g.
# Vercel mints a unique "*-<hash>-<team>.vercel.app" URL for every single
# deployment/preview, so exact-matching ALLOWED_ORIGINS alone would need to
# be updated on every deploy. Set this to something like
# https://code-lens.*\.vercel\.app to allow any deployment of your project.
# Leave unset to only allow the exact origins in ALLOWED_ORIGINS.
ALLOWED_ORIGIN_REGEX = os.environ.get("ALLOWED_ORIGIN_REGEX", "").strip() or None

app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS,
    allow_origin_regex=ALLOWED_ORIGIN_REGEX,
    allow_credentials=False,
    allow_methods=["GET", "POST", "OPTIONS"],
    allow_headers=["Content-Type", "Authorization", "X-API-Key"],
)

# ---------------------------------------------------------------------------
# Request body size limit — defense in depth ahead of per-field validation
# ---------------------------------------------------------------------------

MAX_BODY_BYTES = 100 * 1024  # 100 KB


class BodySizeLimitMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        content_length = request.headers.get("content-length")
        if content_length is not None:
            try:
                too_big = int(content_length) > MAX_BODY_BYTES
            except ValueError:
                too_big = False
            if too_big:
                return JSONResponse(
                    status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
                    content={
                        "error": "payload_too_large",
                        "detail": f"Request body exceeds {MAX_BODY_BYTES} bytes.",
                    },
                )
        return await call_next(request)


app.add_middleware(BodySizeLimitMiddleware)

# ---------------------------------------------------------------------------
# API-key auth
# ---------------------------------------------------------------------------

API_KEY = os.environ.get("API_KEY", "").strip()

if not API_KEY:
    logger.warning(
        "API_KEY is not set — all /api/v1/* routes are UNAUTHENTICATED. "
        "Set the API_KEY environment variable before deploying publicly."
    )

# Multi-worker deployments (e.g. `uvicorn --workers N` or a process manager
# fanning out several instances) each get their OWN copy of the in-memory
# rate-limit stores and analyze-result cache below — they do not coordinate
# with each other, so the effective rate limit is (per-worker limit) x
# (worker count), not the configured limit. Warn loudly if that looks likely.
_WORKERS = os.environ.get("WORKERS", "").strip()
if _WORKERS and _WORKERS not in ("0", "1"):
    logger.warning(
        "WORKERS=%s suggests a multi-process deployment. The in-memory rate "
        "limiter and result caches in this app are per-process ONLY and do "
        "NOT coordinate across workers/instances. For correct global rate "
        "limiting behind multiple workers or replicas, use a shared backend "
        "(e.g. Redis) instead.",
        _WORKERS,
    )


async def require_api_key(
    x_api_key: str | None = Header(default=None, alias="X-API-Key")
) -> None:
    """FastAPI dependency enforcing the X-API-Key header on protected routes."""
    if not API_KEY:
        return  # auth disabled — no key configured (local/dev convenience)
    if not x_api_key or x_api_key != API_KEY:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing or invalid X-API-Key header.",
        )


async def _is_trusted_caller(
    x_api_key: str | None = Header(default=None, alias="X-API-Key")
) -> bool:
    """
    Non-enforcing check used only by /api/health to decide whether to reveal
    `ai_available` — the health check itself stays public/unauthenticated,
    but we don't want to tell anonymous callers whether a paid API key is
    configured server-side.
    """
    if not API_KEY:
        return True  # auth disabled entirely -> health stays fully public
    return bool(x_api_key) and x_api_key == API_KEY


# ---------------------------------------------------------------------------
# In-memory rate limiter (per-process, TTL-evicted so it can't grow forever)
# ---------------------------------------------------------------------------
# NOTE: this limiter is per-process / in-memory — see the WORKERS warning
# above. It will NOT coordinate across multiple Uvicorn workers or multiple
# instances behind a load balancer. For real multi-instance deployments,
# replace this with a Redis-backed limiter.

TRUSTED_PROXY = os.environ.get("TRUSTED_PROXY", "false").strip().lower() in ("1", "true", "yes")

RATE_LIMIT_REQUESTS = 20    # max requests per window
RATE_LIMIT_WINDOW = 60.0    # seconds

# Separate, tighter limit for AI explanation calls (costs money)
AI_RATE_LIMIT_REQUESTS = 15
AI_RATE_LIMIT_WINDOW = 60.0

# TTLCache bounds memory two ways: maxsize caps the number of distinct IPs
# tracked at once (LRU-evicting the oldest once full), and ttl automatically
# drops an IP's entry once it's been quiet for two full windows — unlike a
# plain dict/defaultdict, which only ever grows.
_rate_store: TTLCache = TTLCache(maxsize=10_000, ttl=RATE_LIMIT_WINDOW * 2)
_ai_rate_store: TTLCache = TTLCache(maxsize=10_000, ttl=AI_RATE_LIMIT_WINDOW * 2)


def _client_ip(request: Request) -> str:
    """
    Resolve the caller's IP for rate-limiting purposes.

    X-Forwarded-For is only trusted when TRUSTED_PROXY=true. This app may be
    exposed directly (not always behind a proxy that sets/sanitises that
    header), and a direct caller could otherwise forge a fresh IP on every
    request to bypass the limiter entirely. Only enable TRUSTED_PROXY when
    you control the upstream proxy/load balancer and know it always
    overwrites (never appends to) client-supplied X-Forwarded-For values.
    """
    if TRUSTED_PROXY:
        forwarded = request.headers.get("x-forwarded-for")
        if forwarded:
            return forwarded.split(",")[0].strip()
    return request.client.host if request.client else "unknown"


def _check_rate_limit(ip: str) -> None:
    now = time.monotonic()
    window_start = now - RATE_LIMIT_WINDOW
    timestamps = [t for t in _rate_store.get(ip, []) if t > window_start]
    if len(timestamps) >= RATE_LIMIT_REQUESTS:
        _rate_store[ip] = timestamps
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail=(
                f"Rate limit exceeded: max {RATE_LIMIT_REQUESTS} requests "
                f"per {int(RATE_LIMIT_WINDOW)}s."
            ),
        )
    timestamps.append(now)
    _rate_store[ip] = timestamps


def _check_ai_rate_limit(ip: str) -> bool:
    """Returns False (and does NOT raise) if the AI limit is hit — AI is optional."""
    now = time.monotonic()
    window_start = now - AI_RATE_LIMIT_WINDOW
    timestamps = [t for t in _ai_rate_store.get(ip, []) if t > window_start]
    if len(timestamps) >= AI_RATE_LIMIT_REQUESTS:
        _ai_rate_store[ip] = timestamps
        return False
    timestamps.append(now)
    _ai_rate_store[ip] = timestamps
    return True


_AI_LIMIT_MESSAGE = {
    "explanation": "AI explanation rate limit reached. Please wait a moment and try again.",
    "model": None,
    "cached": False,
    "error": True,
}

# ---------------------------------------------------------------------------
# /api/analyze result cache — short-circuits the whole validate -> extract ->
# simulate pipeline for repeat identical (code, cache_config) submissions.
# TTL-bounded (not just size-bounded) so stale entries don't linger forever.
# ---------------------------------------------------------------------------

_analyze_cache: TTLCache = TTLCache(maxsize=1024, ttl=300)


def _analyze_cache_key(code: str, cfg: CacheConfig, include_debug: bool) -> str:
    payload = json.dumps(
        {
            "code": code,
            "cache_config": cfg.model_dump(),
            "include_debug": include_debug,
        },
        sort_keys=True,
    )
    return hashlib.sha256(payload.encode()).hexdigest()


# ---------------------------------------------------------------------------
# Request / response schemas
# ---------------------------------------------------------------------------

MAX_CODE_BYTES = 1024
MAX_METADATA_STRING_LEN = 200
MAX_METADATA_LIST_LEN = 10


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

    @property
    def num_sets(self) -> int:
        return self.size_bytes // (self.block_size_bytes * self.associativity)

    @model_validator(mode="after")
    def check_num_sets(self) -> CacheConfig:
        # Defense in depth: the divisibility check above already makes this
        # unreachable in practice (size_bytes >= 64 and a valid divisor
        # implies num_sets >= 1), but this is the single, shared place both
        # /analyze and /optimize used to duplicate this check inline.
        if self.num_sets < 1:
            raise ValueError(
                "Cache configuration results in zero sets. Increase size_bytes or decrease associativity."
            )
        return self


class CodeRequestBase(BaseModel):
    """Shared fields/validators for /analyze and /optimize request bodies."""

    code: str = Field(..., min_length=1, description="Python code to submit (max 1 KB).")
    cache_config: CacheConfig = Field(default_factory=CacheConfig)

    @field_validator("code")
    @classmethod
    def check_code_length(cls, v: str) -> str:
        if len(v.encode()) > MAX_CODE_BYTES:
            raise ValueError(
                f"Code too long: {len(v.encode())} bytes (max {MAX_CODE_BYTES})."
            )
        return v


class AnalyzeRequest(CodeRequestBase):
    include_ai_explanation: bool = Field(
        default=False,
        description="If true, call the AI layer for a plain-English explanation. Costs money — opt-in only.",
    )
    include_debug: bool = Field(
        default=False,
        description="Dev-only: if true, response includes first 50 raw byte addresses generated.",
    )


class OptimizeRequest(CodeRequestBase):
    include_ai_explanation: bool = Field(
        default=False,
        description="If true, generate an AI summary of the before/after comparison.",
    )


class SimulateMetadata(BaseModel):
    """
    Strict, size-capped shape for the optional caller-supplied metadata on
    /api/simulate. Prevents arbitrary attacker-controlled content from being
    interpolated into the LLM prompt in explanation_generator.py (prompt
    injection / unbounded token cost) — unknown fields are rejected (422)
    and every string/list is length-capped.
    """

    model_config = {"extra": "forbid"}

    pattern_type: str | None = Field(default=None, max_length=MAX_METADATA_STRING_LEN)
    access_order: str | None = Field(default=None, max_length=MAX_METADATA_STRING_LEN)
    summary: str | None = Field(default=None, max_length=MAX_METADATA_STRING_LEN)
    locality: str | None = Field(default=None, max_length=MAX_METADATA_STRING_LEN)
    cache_efficiency: str | None = Field(default=None, max_length=MAX_METADATA_STRING_LEN)
    stride: int | None = None
    array_dimensions: list[int] | None = Field(default=None, max_length=MAX_METADATA_LIST_LEN)
    issues: list[str] | None = Field(default=None, max_length=MAX_METADATA_LIST_LEN)
    suggestions: list[str] | None = Field(default=None, max_length=MAX_METADATA_LIST_LEN)

    @field_validator("issues", "suggestions")
    @classmethod
    def cap_item_length(cls, v: list[str] | None) -> list[str] | None:
        if v is None:
            return v
        for item in v:
            if len(item) > MAX_METADATA_STRING_LEN:
                raise ValueError(
                    f"Metadata list items must be at most {MAX_METADATA_STRING_LEN} characters."
                )
        return v


class SimulateRequest(BaseModel):
    addresses: list[int] = Field(
        ..., description="Byte addresses to simulate (max 50,000 integers)."
    )
    cache_config: CacheConfig = Field(default_factory=CacheConfig)
    include_ai_explanation: bool = Field(default=False)
    metadata: SimulateMetadata | None = Field(
        default=None, description="Optional pattern metadata for the AI explanation."
    )

    @field_validator("addresses")
    @classmethod
    def check_addresses(cls, v: list[int]) -> list[int]:
        if len(v) > 50_000:
            raise ValueError("'addresses' must contain at most 50,000 integers.")
        return v


# ---------------------------------------------------------------------------
# Error handling — every error path returns the same {"error", "detail"} shape
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


@app.exception_handler(ValueError)
async def value_error_handler(request: Request, exc: ValueError) -> JSONResponse:
    return JSONResponse(
        status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
        content={"error": "invalid_request", "detail": str(exc)},
    )


@app.exception_handler(TypeError)
async def type_error_handler(request: Request, exc: TypeError) -> JSONResponse:
    return JSONResponse(
        status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
        content={"error": "invalid_request", "detail": str(exc)},
    )


@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    logger.exception("Unhandled exception on %s %s", request.method, request.url.path)
    return JSONResponse(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        content={"error": "internal_error", "detail": "An unexpected error occurred."},
    )


# ---------------------------------------------------------------------------
# Health check — unauthenticated, but gates the ai_available flag
# ---------------------------------------------------------------------------


async def health(trusted: bool = Depends(_is_trusted_caller)) -> dict:
    payload: dict = {
        "status": "ok",
        "version": app.version,
        "cache_default": {
            "size_bytes": 512,
            "block_size_bytes": 64,
            "associativity": 2,
            "num_sets": 4,
        },
    }
    if trusted:
        payload["ai_available"] = bool(os.environ.get("ANTHROPIC_API_KEY", "").strip())
    return payload


app.add_api_route("/api/health", health, methods=["GET"], tags=["meta"])
app.add_api_route("/api/v1/health", health, methods=["GET"], tags=["meta"])


# ---------------------------------------------------------------------------
# Versioned, authenticated routes
# ---------------------------------------------------------------------------

router = APIRouter(prefix="/api/v1", dependencies=[Depends(require_api_key)])


@router.post("/analyze", tags=["analysis"])
async def analyze(request: Request, body: AnalyzeRequest) -> dict:
    """
    Analyze a Python code snippet for cache efficiency.

    Steps:
      1. Rate-limit check (general)
      2. Result-cache lookup (hash of code + cache_config)
      3. AST whitelist validation (returns 422 on failure with a clear message)
      4. Static / dynamic access-trace extraction
      5. CacheSimulator run
      6. Metadata assembly
      7. (Optional) AI explanation via Claude — rate-limited separately, opt-in
    """
    ip = _client_ip(request)
    _check_rate_limit(ip)

    cfg = body.cache_config
    cache_key = _analyze_cache_key(body.code, cfg, body.include_debug)
    cached = _analyze_cache.get(cache_key)
    if cached is not None:
        result = copy.deepcopy(cached)
    else:
        result = analyze_code(
            code=body.code,
            cache_size_bytes=cfg.size_bytes,
            block_size_bytes=cfg.block_size_bytes,
            associativity=cfg.associativity,
            include_debug=body.include_debug,
        )
        _analyze_cache[cache_key] = copy.deepcopy(result)

    if body.include_ai_explanation:
        if _check_ai_rate_limit(ip):
            result["ai_explanation"] = generate_explanation(result)
        else:
            result["ai_explanation"] = dict(_AI_LIMIT_MESSAGE)

    return result


@router.post("/optimize", tags=["analysis"])
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
    ip = _client_ip(request)
    _check_rate_limit(ip)

    cfg = body.cache_config
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
            result["ai_explanation"] = dict(_AI_LIMIT_MESSAGE)

    return result


@router.get("/gallery", tags=["gallery"])
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


@router.get("/gallery/{item_id}", tags=["gallery"])
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


@router.post("/simulate", tags=["analysis"])
async def simulate_raw(request: Request, body: SimulateRequest) -> dict:
    """
    Lower-level endpoint: accept a raw list of addresses and return cache stats.
    Useful for frontend demos without code submission.
    """
    ip = _client_ip(request)
    _check_rate_limit(ip)

    cfg = body.cache_config
    # Cap retained AccessRecord objects — the response only ever serialises
    # at most 4096 of them anyway, so there's no reason to hold up to 50,000
    # dataclass instances in memory for the duration of the request.
    sim = CacheSimulator(
        cfg.size_bytes, cfg.block_size_bytes, cfg.associativity, max_log_records=4096
    )
    for addr in body.addresses:
        sim.access(addr)

    result: dict = {
        "cache_stats": sim.stats(),
        "access_log": sim.access_log_as_dicts(max_records=4096),
    }

    if body.include_ai_explanation:
        if _check_ai_rate_limit(ip):
            explanation_input = {
                "cache_stats": result["cache_stats"],
                "metadata": body.metadata.model_dump(exclude_none=True) if body.metadata else {},
            }
            result["ai_explanation"] = generate_explanation(explanation_input)
        else:
            result["ai_explanation"] = dict(_AI_LIMIT_MESSAGE)

    return result


app.include_router(router)
