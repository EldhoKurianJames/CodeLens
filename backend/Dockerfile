FROM python:3.12-slim

WORKDIR /app

# Install dependencies first so this layer is cached across code-only changes.
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

EXPOSE 8000

# No --reload in production images; run as a plain single-process server.
# For multi-worker deployments set WORKERS and add --workers $WORKERS below,
# but remember the in-memory rate limiter / caches are per-process (see
# main.py) — prefer a single worker unless you've moved those to Redis.
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
