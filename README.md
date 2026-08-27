# CacheLens AI

A full-stack tool that analyzes user-submitted Python code, simulates its real memory access
pattern through a configurable cache simulator, and identifies cache-inefficiency issues.

## Project Structure

```
cachelens-ai/
├── backend/                    # FastAPI application
│   ├── cache_simulator.py      # LRU set-associative cache model
│   ├── code_analyzer.py        # AST validator + access-trace extractor
│   ├── code_optimizer.py       # Loop-interchange auto-optimizer + re-simulation
│   ├── sandbox_worker.py       # Isolated subprocess execution worker
│   ├── explanation_generator.py # Claude (Anthropic) explanation layer
│   ├── gallery.py              # Pre-generated algorithm demo traces
│   ├── main.py                 # FastAPI routes, auth, rate limiting
│   ├── requirements.txt
│   ├── pyproject.toml          # ruff lint config
│   ├── pytest.ini
│   ├── Dockerfile
│   └── tests/
└── frontend/                   # React + Vite + TypeScript
    ├── src/
    ├── Dockerfile               # multi-stage build, served via nginx
    ├── eslint.config.js
    └── .prettierrc.json
```

## Tech Stack

- **Backend**: Python 3.12, FastAPI, Uvicorn
- **Frontend**: React (Vite) + TypeScript, TailwindCSS, Monaco Editor, D3.js, Recharts
- **Deployment**: Docker Compose (recommended, cross-platform) or Render (backend) + Vercel (frontend)

## Running Locally with Docker (recommended, cross-platform)

This is the easiest way to run the full stack and matches how it would be deployed.

```bash
cp .env.example backend/.env      # fill in ANTHROPIC_API_KEY, API_KEY, etc.
docker compose up --build
```

- Backend: http://localhost:8000
- Frontend: http://localhost:5173

Environment variables read by `docker-compose.yml` (export them in your shell, or put them in a
`.env` file at the repo root — Compose auto-loads that): `ANTHROPIC_API_KEY`, `API_KEY`,
`ALLOWED_ORIGINS`, `TRUSTED_PROXY`, `VITE_API_URL`, `VITE_API_KEY`.

## Running Locally without Docker

### Backend

```powershell
cd backend
pip install -r requirements-dev.txt   # installs requirements.txt + pytest/httpx/ruff for local dev
cp ../.env.example .env   # fill in ANTHROPIC_API_KEY / API_KEY / etc., or export them directly
python -m uvicorn main:app --port 8000 --host 127.0.0.1
```

> `requirements.txt` is intentionally minimal (production runtime only) to keep the deployed
> container's memory footprint small on memory-capped hosts (e.g. Render's 512Mi free/starter
> tier) — use `requirements-dev.txt` locally and in CI for testing/linting.

> **Windows note:** do NOT use `--reload` — it spawns a subprocess blocked by Windows Application
> Control policy in some locked-down environments.

Run tests:
```powershell
cd backend
pytest tests/ -v
```

Lint:
```powershell
cd backend
pip install ruff
ruff check .
```

### Frontend
npm.cmd run dev
```powershell
cd frontend
npm install
cp .env.example .env   # set VITE_API_URL / VITE_API_KEY to match the backend
npm run dev
```

> **Windows PowerShell note:** if `npm`/`npx` scripts are blocked by execution policy, use
> `npm.cmd`/`npx.cmd` instead (or run `node -e "require('child_process').spawn(...)"` as a
> workaround), rather than changing the system execution policy.

Build / lint:
```powershell
npm run build
npm run lint
```

## Environment Variables

Backend (see `.env.example`, loaded from `backend/.env`):

| Variable | Default | Notes |
|---|---|---|
| `ANTHROPIC_API_KEY` | *(unset)* | Enables AI explanations. Without it, `/api/v1/analyze` etc. still work — the AI section just returns a graceful fallback message. |
| `API_KEY` | *(unset)* | Required in any non-local deployment. Clients must send it as the `X-API-Key` header on every `/api/v1/*` request. **If unset, auth is disabled** — a startup warning is logged; do not deploy publicly without setting this. |
| `ALLOWED_ORIGINS` | `http://localhost:5173` | Comma-separated list of origins allowed by CORS. Add your deployed frontend URL(s) here in production. |
| `TRUSTED_PROXY` | `false` | Only set `true` if a proxy/load balancer you control always overwrites `X-Forwarded-For` before it reaches this app; used for rate-limiting by real client IP. |
| `WORKERS` | *(unset)* | Informational only — set it to whatever worker/replica count you actually run, so the app can warn you that its in-memory rate limiter and caches are per-process (see below). |

Frontend (see `frontend/.env.example`):

| Variable | Default | Notes |
|---|---|---|
| `VITE_API_URL` | `http://127.0.0.1:8000` | Backend base URL. |
| `VITE_API_KEY` | *(unset)* | Must match the backend's `API_KEY`. Sent as `X-API-Key` on every request. |

## Deployment Notes

- **Backend**: build `backend/Dockerfile` and deploy anywhere that runs containers (Render, Fly.io,
  Railway, ECS, etc.), or use a platform's native Python buildpack with
  `uvicorn main:app --host 0.0.0.0 --port $PORT`. Set `API_KEY`, `ANTHROPIC_API_KEY`, and
  `ALLOWED_ORIGINS` (to your deployed frontend's exact origin) as environment variables on the
  platform.
- **Frontend**: build `frontend/Dockerfile` (bakes `VITE_API_URL`/`VITE_API_KEY` in as build args),
  or deploy the static `npm run build` output (`frontend/dist`) directly to Vercel/Netlify/Cloudflare
  Pages, setting `VITE_API_URL`/`VITE_API_KEY` as build-time environment variables there.
- **Rate limiting / caching are per-process**: the hand-rolled rate limiter and the `/api/v1/analyze`
  result cache in `backend/main.py` live in memory inside a single Uvicorn process. Running multiple
  workers or multiple backend instances behind a load balancer means each one enforces its own
  independent limit/cache — they do not coordinate. This is fine for a single small deployment; for
  real horizontal scaling, replace both with a Redis-backed implementation.
- **CI**: `.github/workflows/ci.yml` runs `ruff check` + `pytest` for the backend and
  `eslint` + `tsc`/`vite build` for the frontend on every push/PR to `master`.

## API Versioning

Routes live under `/api/v1/...` (e.g. `/api/v1/analyze`, `/api/v1/optimize`, `/api/v1/gallery`,
`/api/v1/simulate`) and require the `X-API-Key` header described above. `/api/health` (and its alias
`/api/v1/health`) is intentionally unauthenticated so load balancers / uptime checks can call it
without a key; it only reveals whether AI explanations are configured (`ai_available`) to callers
who *do* supply a valid key.

## Phases

| Phase | Status | Description |
|-------|--------|-------------|
| 1 | ✅ Done | Cache simulator + AST-based access-pattern extractor + tests |
| 2 | ✅ Done | FastAPI backend with `/api/analyze`, `/api/health`, algorithm gallery |
| 3 | ✅ Done | LLM explanation layer (Claude via Anthropic API) |
| 4 | ✅ Done | React frontend (Vite + TypeScript + Tailwind) |
| 5 | ✅ Done | Security/perf hardening: API-key auth, versioned API, rate-limit fixes, sandbox hardening, Docker, CI |

## Cache Configuration Defaults

| Parameter | Default | Notes |
|-----------|---------|-------|
| `cache_size_bytes` | 512 | Small enough to show dramatic hit-rate deltas |
| `block_size_bytes` | 64 | 16 × 4-byte ints per block |
| `associativity` | 2 | 2-way LRU per set → 4 sets total |

With these parameters, row-major traversal of a 64×64 int matrix hits **~93.75%**;
column-major hits **~0–3%**.
