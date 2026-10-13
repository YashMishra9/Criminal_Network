# AI-Powered Criminal Network Analysis System

A research/demonstration system for visualising and analysing criminal networks using entity extraction, graph analysis, and an LLM-assisted question-answering layer.

> **Data note**: this system is designed to run entirely on synthetic demonstration data. No real personal data is stored or processed by default.

---

## Table of Contents

1. [Architecture Overview](#architecture-overview)
2. [Local Development](#local-development)
3. [Deployment](#deployment)
   - [Backend — Render or Railway](#backend--render-or-railway)
   - [Frontend — Vercel](#frontend--vercel)
   - [Database — Neo4j Aura](#database--neo4j-aura)
   - [Environment Variables Reference](#environment-variables-reference)
   - [Smoke Testing the Deployment](#smoke-testing-the-deployment)
4. [Configuration](#configuration)
5. [Testing](#testing)

---

## Architecture Overview

| Layer | Technology | Notes |
|---|---|---|
| Frontend | Next.js (React + TypeScript) | Deployed to Vercel |
| Backend | Python + FastAPI | Deployed to Render or Railway (Docker) |
| Database | Neo4j | Neo4j Aura (managed) or self-hosted |
| LLM | Configurable (mock by default) | OpenAI / Gemini / Anthropic or mock |

See `docs/DOC2_ARCHITECTURE.md §15` for the authoritative deployment architecture.

---

## Local Development

### Prerequisites

- Python 3.11+
- Node.js 18+
- A running Neo4j instance (local or Neo4j Aura)

### Backend

```bash
# From the repo root
cd backend
pip install -r requirements.txt

# Copy and configure environment
cp config/.env.example config/.env
# Edit config/.env — set NEO4J_URI, NEO4J_USER, NEO4J_PASSWORD

# Run the development server
uvicorn app.main:app --reload --port 8000
```

### Frontend

```bash
cd frontend
npm install
npm run dev
```

### Running Tests

```bash
cd backend
python -m pytest -q --tb=short
```

---

## Deployment

The system deploys to three platforms (DOC2 §15):

| Component | Platform | Config file |
|---|---|---|
| Frontend | Vercel | `frontend/vercel.json` |
| Backend | Render **or** Railway | `render.yaml` / `railway.toml` |
| Database | Neo4j Aura | (managed — no config file) |

> ⚠️ **Contract Invariant 7**: `LIVE_ADAPTER_ENABLED` **must default to `false`** in all deployed configurations. This ensures the demo runs fully offline from external data dependencies. Override it explicitly only when intentionally demonstrating the optional live-data extension.

---

### Backend — Render or Railway

The backend is packaged as a Docker container (`backend/Dockerfile`).

#### Option A: Render

1. Create a new Render account or sign in at [render.com](https://render.com).
2. Click **New → Blueprint** and connect this repository.
3. Render auto-detects `render.yaml` and creates the `criminal-network-backend` web service.
4. In the Render dashboard → **criminal-network-backend → Environment**, add the following **secret** environment variables:

   | Variable | Description |
   |---|---|
   | `NEO4J_URI` | Neo4j connection URI (e.g. `neo4j+s://<id>.databases.neo4j.io`) |
   | `NEO4J_USER` | Neo4j username (typically `neo4j`) |
   | `NEO4J_PASSWORD` | Neo4j password |
   | `LLM_API_KEY` | LLM provider API key (leave blank if `LLM_PROVIDER=mock`) |

5. Leave `LIVE_ADAPTER_ENABLED=false` (already set in `render.yaml`).
6. Click **Deploy** — Render will build the Docker image and start the service.

#### Option B: Railway

1. Create a new Railway project at [railway.app](https://railway.app).
2. Click **New Project → Deploy from GitHub Repo** and connect this repository.
3. Railway detects `railway.toml` and builds from `backend/Dockerfile`.
4. In the Railway dashboard → **Variables**, add:

   | Variable | Description |
   |---|---|
   | `NEO4J_URI` | Neo4j connection URI |
   | `NEO4J_USER` | Neo4j username |
   | `NEO4J_PASSWORD` | Neo4j password |
   | `LLM_API_KEY` | LLM provider API key (omit if `LLM_PROVIDER=mock`) |

5. Leave `LIVE_ADAPTER_ENABLED=false` (already set in `railway.toml`).
6. Railway will trigger a build and deployment automatically.

---

### Frontend — Vercel

1. Sign in at [vercel.com](https://vercel.com).
2. Click **New Project** and import this repository.
3. Set **Root Directory** to `frontend`.
4. Vercel detects `frontend/vercel.json` (Next.js framework auto-detected).
5. In the Vercel dashboard → **Settings → Environment Variables**, set:

   | Variable | Value |
   |---|---|
   | `NEXT_PUBLIC_API_BASE_URL` | Your backend URL (e.g. `https://criminal-network-backend.onrender.com/api/v1`) |

6. Click **Deploy**.

> **Update `frontend/vercel.json`**: replace `"https://your-backend-url.onrender.com/api/v1"` with your actual backend URL before the first deploy.

---

### Database — Neo4j Aura

1. Create a free/dev instance at [console.neo4j.io](https://console.neo4j.io).
2. Copy the **Connection URI**, **Username**, and **Password**.
3. Set these as `NEO4J_URI`, `NEO4J_USER`, `NEO4J_PASSWORD` in your backend platform's environment.
4. After the backend is running, apply the graph schema:

   ```bash
   # From the repo root, with NEO4J_* env vars set:
   python -c "from app.graph.schema import apply_schema; apply_schema()"
   ```

   Or trigger it via the ingestion API endpoint once the backend is live.

**Self-hosted fallback**: if Neo4j Aura's free tier does not fit your dataset, run Neo4j in Docker:

```bash
docker run \
  --name neo4j \
  -p 7474:7474 -p 7687:7687 \
  -e NEO4J_AUTH=neo4j/your-password \
  neo4j:5
```

---

### Environment Variables Reference

| Variable | Default | Required in prod | Description |
|---|---|---|---|
| `ENVIRONMENT` | `development` | Yes (`production`) | Activates strict config validation |
| `DEFAULT_DATASET` | `synthetic_demo` | No | Default dataset scope for all read operations |
| `LIVE_ADAPTER_ENABLED` | **`false`** | **Never change without intent** | Contract Invariant 7 — must be false for the offline demo path |
| `NEO4J_URI` | `bolt://localhost:7687` | Yes | Neo4j connection URI |
| `NEO4J_USER` | `neo4j` | Yes | Neo4j username |
| `NEO4J_PASSWORD` | `password` | Yes (set as secret) | Neo4j password |
| `LLM_PROVIDER` | `mock` | No | LLM backend: `mock`, `openai`, `gemini`, `anthropic` |
| `LLM_API_KEY` | _(empty)_ | Only if LLM_PROVIDER != mock | API key for the chosen LLM provider |
| `PORT` | `8000` | No (injected by platform) | Port uvicorn listens on |

---

### Smoke Testing the Deployment

A smoke-test script (`scripts/smoke_test_deploy.py`) verifies the Docker build and container startup locally, and checks that `LIVE_ADAPTER_ENABLED=false` is enforced in the running container.

**Requirements**: Docker daemon must be running.

```bash
# From the repo root:
python scripts/smoke_test_deploy.py
```

The script:
1. Builds the Docker image from `backend/Dockerfile`.
2. Starts a container on port 18080.
3. Polls `http://localhost:18080/docs` until 200 OK.
4. Verifies `LIVE_ADAPTER_ENABLED=false` inside the container (Contract Invariant 7).
5. Stops and removes the container.

Exits `0` on success, `1` on any failure.

---

## Configuration

Copy `config/.env.example` to `config/.env` and fill in values for local development. The `.env` file is never committed (it is `.gitignore`'d).

```bash
cp config/.env.example config/.env
```

For platform deployments, set all required variables via the platform's secret/environment management (not via committed files).

---

## Testing

```bash
cd backend

# Run all tests (unit + integration stubs)
python -m pytest -q --tb=short

# Run only unit tests
python -m pytest tests/unit/ -q

# Run live-Neo4j tests (requires a running Neo4j instance)
python -m pytest -m neo4j_live -q
```
