# syntax=docker/dockerfile:1.7
# MiroFish dev/runtime image
# - Builds frontend with vite + runs Flask backend
# - Memory backend = LightRAG + FalkorDB (reached via compose service "falkordb")
# - First container start downloads BAAI/bge-* models to /root/.cache/huggingface

FROM python:3.11-slim

# ===== System packages =====
# - nodejs/npm: build & dev-serve the Vue frontend
# - git/curl: sentence-transformers may resolve some HF repos via git; curl for healthchecks
# - build-essential: wheels for tokenizers / sentence-transformers fallback compile path
RUN apt-get update \
 && apt-get install -y --no-install-recommends \
      nodejs npm git curl ca-certificates build-essential \
 && rm -rf /var/lib/apt/lists/*

# ===== uv (Python deps manager) =====
COPY --from=ghcr.io/astral-sh/uv:0.9.26 /uv /uvx /bin/

WORKDIR /app

# ----- Dependency layer (cache-friendly) -----
# Copy only manifests so a code change doesn't bust dep caches.
COPY package.json package-lock.json ./
COPY frontend/package.json frontend/package-lock.json ./frontend/
COPY backend/pyproject.toml backend/uv.lock ./backend/

RUN npm ci \
 && npm ci --prefix frontend \
 && cd backend && uv sync --frozen

# ----- Application source -----
COPY . .

# ===== Runtime config =====
# Default to Graphiti + local Neo4j; ports match the upstream image.
ENV PYTHONUNBUFFERED=1 \
    FLASK_HOST=0.0.0.0 \
    FLASK_PORT=5001 \
    MEMORY_BACKEND=lightrag \
    FALKORDB_HOST=falkordb \
    FALKORDB_PORT=6379 \
    HF_HOME=/root/.cache/huggingface

EXPOSE 3000 5001

# Healthcheck against the Flask backend
HEALTHCHECK --interval=30s --timeout=5s --start-period=60s --retries=3 \
  CMD curl -fsS http://127.0.0.1:5001/health || exit 1

# Run both processes concurrently via the existing npm script
# (`npm run dev` -> concurrently backend + frontend)
CMD ["npm", "run", "dev"]
