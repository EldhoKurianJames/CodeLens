# CacheLens AI

A full-stack tool that analyzes user-submitted Python code, simulates its real memory access
pattern through a configurable cache simulator, and identifies cache-inefficiency issues.

## Project Structure

```
cachelens-ai/
├── backend/           # FastAPI application
│   ├── cache_simulator.py    # LRU set-associative cache model
│   ├── code_analyzer.py      # AST validator + access-trace extractor
│   ├── sandbox_worker.py     # Isolated subprocess execution worker
│   ├── gallery.py            # Pre-generated algorithm demo traces
│   ├── main.py               # FastAPI routes
│   ├── requirements.txt
│   └── tests/
│       └── test_phase1.py    # Cache + analyzer pytest suite
└── frontend/          # React + Vite + TypeScript (Phase 3)
```

## Tech Stack

- **Backend**: Python 3.11+, FastAPI, Uvicorn
- **Frontend** *(Phase 3)*: React (Vite) + TypeScript, TailwindCSS, Monaco Editor, D3.js, Recharts
- **Deployment** *(later)*: Render (backend) + Vercel (frontend)

## Phases

| Phase | Status | Description |
|-------|--------|-------------|
| 1 | ✅ Done | Cache simulator + AST-based access-pattern extractor + tests |
| 2 | ✅ Done | FastAPI backend with `/api/analyze`, `/api/health`, algorithm gallery |
| 3 | ✅ Done | LLM explanation layer (Claude via Anthropic API) |
| 4 | ✅ Done | React frontend (Vite + TypeScript + Tailwind) |

## Running Locally

```powershell
cd backend
pip install -r requirements.txt
py -3.13 -m uvicorn main:app --port 8000 --host 127.0.0.1
```

> **Note:** do NOT use `--reload` — it spawns a subprocess blocked by Windows Application Control policy.

Run tests:
```powershell
cd backend
py -3.13 -m pytest tests/ -v
```

Frontend (PowerShell — use `node` due to execution policy):
```powershell
node -e "require('child_process').spawn('npx', ['vite', '--port', '5173'], {cwd: 'd:/CodeLens-Project/frontend', stdio: 'inherit', shell: true})"
```

## Cache Configuration Defaults

| Parameter | Default | Notes |
|-----------|---------|-------|
| `cache_size_bytes` | 512 | Small enough to show dramatic hit-rate deltas |
| `block_size_bytes` | 64 | 16 × 4-byte ints per block |
| `associativity` | 2 | 2-way LRU per set → 4 sets total |

With these parameters, row-major traversal of a 64×64 int matrix hits **~93.75%**;
column-major hits **~0–3%**.
http://localhost:5173/