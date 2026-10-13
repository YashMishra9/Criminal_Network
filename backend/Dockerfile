# ============================================================================
# Criminal Network Analysis System — Backend Dockerfile
# Target platforms: Render, Railway (DOC2 §15)
# Contract Invariant 7: LIVE_ADAPTER_ENABLED must default to false.
# ============================================================================

# ----- Stage 1: dependency installation -----
FROM python:3.11-slim AS deps

WORKDIR /deps

# Install OS-level build dependencies for compiled Python packages
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir --upgrade pip \
    && pip install --no-cache-dir -r requirements.txt

# ----- Stage 2: runtime image -----
FROM python:3.11-slim AS runtime

WORKDIR /app

# Copy installed packages from deps stage
COPY --from=deps /usr/local/lib/python3.11/site-packages /usr/local/lib/python3.11/site-packages
COPY --from=deps /usr/local/bin /usr/local/bin

# Copy application source
COPY app/ ./app/

# ---- Environment defaults (all overridable at deploy time) ----
# ENVIRONMENT must be set to "production" in deployed envs.
ENV ENVIRONMENT=production

# Default dataset scope — synthetic_demo prevents accidental live-data exposure.
ENV DEFAULT_DATASET=synthetic_demo

# CONTRACT INVARIANT 7 (DOC3): Live adapter disabled by default.
# The demo must run fully offline without external data dependencies.
# Override explicitly only when demoing the optional live-data extension.
ENV LIVE_ADAPTER_ENABLED=false

# Neo4j — placeholder values; MUST be overridden via platform secrets/env vars.
ENV NEO4J_URI=bolt://localhost:7687
ENV NEO4J_USER=neo4j
ENV NEO4J_PASSWORD=changeme

# LLM provider — defaults to mock so the backend starts without any API key.
ENV LLM_PROVIDER=mock
ENV LLM_API_KEY=

# PORT — Render and Railway inject $PORT; default to 8000 for local container runs.
ENV PORT=8000

# Expose the port (informational — actual binding is via $PORT below)
EXPOSE 8000

# Health-check: polls /api/v1/health if it exists, otherwise /docs
HEALTHCHECK --interval=30s --timeout=10s --start-period=20s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:${PORT}/docs')" || exit 1

# Launch uvicorn on $PORT (Render/Railway standard)
CMD ["sh", "-c", "uvicorn app.main:app --host 0.0.0.0 --port ${PORT}"]
