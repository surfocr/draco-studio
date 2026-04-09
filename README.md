# Draco Dataset Studio

Draco Dataset Studio is a local-first dataset curation platform for LoRA training, diffusion fine-tuning, identity datasets, portrait/style datasets, product/object datasets, aesthetic libraries, and social-media-ready media collections.

This repo contains:

- a React + TypeScript frontend (Vite)
- a FastAPI backend (Python 3.11+)
- provider-based AI/ML integrations for captioning, embeddings, face analysis, ranking, export, and augmentation

## Core Features

- dataset ingest and organization
- caption generation and caption version history
- duplicate and near-duplicate handling
- face-aware analysis
- semantic search foundations
- pairwise ranking and AI-assisted judging
- export workflows for training-ready datasets
- local-first provider setup with Ollama support

## Architecture Overview

- Frontend: `frontend/`
- Backend: `backend/`
- Providers: `backend/providers/`
- Services: `backend/services/`
- ORM models: `backend/models/`
- Alembic migrations: `backend/alembic/versions/`

Runtime/provider design: see `backend/providers/` and `backend/services/runtime_config.py`.

## Project Runtime Configuration

Each project can now choose task-specific providers and options for:

- captioning
- ranking explanations
- dataset coaching
- embeddings
- face detection
- scene understanding
- quality scoring
- ranking engine selection
- outpainting
- image editing

Backend endpoints:

- `GET /api/projects/{project_id}/runtime`
- `PATCH /api/projects/{project_id}/runtime`
- `GET /api/projects/{project_id}/runtime/resolve/{task_key}`

## Provider Configuration

Provider config is persisted in `provider_configs` and re-applied to the live registry on startup.

Useful endpoints:

- `GET /api/providers`
- `GET /api/providers/health`
- `GET /api/providers/configs`
- `POST /api/providers/{provider_type}/config`
- `POST /api/providers/api-key`

## Ollama

Ollama is treated as a first-class local path for captioning and reasoning.

Project runtime task options support:

- `model`
- `temperature`
- `context_length`
- `max_tokens`
- `timeout`
- `batch_size`
- `concurrency`

The Settings UI now lets each project choose different caption/reasoning defaults.

## Developer Setup

### Prerequisites

- Python 3.11+
- Node.js 20+
- npm 10+
- Optional but recommended for local captioning: Ollama

### 1. Install dependencies

From the repo root:

```bash
npm install
```

For the frontend:

```bash
cd frontend
npm install
cd ..
```

For the backend:

```bash
cd backend
pip install -r requirements-dev.txt
cd ..
```

### 2. Create environment files

Backend defaults can live either in repo-root `.env` or `backend/.env`.
The simplest path is:

```bash
cp .env.example .env
cp frontend/.env.example frontend/.env
```

Important notes:

- `.env.example` is tuned for local development and should usually keep `DEBUG=true`.
- `DRACO_SECRET_KEY` should be changed if you plan to save provider API keys through the UI.
- Provider API keys must be saved through the encrypted API-key flow, not generic provider config fields.
- `frontend/.env` should normally point `VITE_API_URL` at `http://127.0.0.1:18082`.

### 3. Start the app

Normal local launch:

```bash
npm start
```

Fastest Windows 11 path:

- double-click [run-portable.bat](run-portable.bat)
- or run:

```bash
npm run start:win
```

What `npm start` does:

- creates missing `.env` and `frontend/.env` files from the checked-in examples
- starts the backend
- waits for `/api/health` to report a healthy backend
- starts the frontend
- opens the app automatically in your browser
- picks a nearby free port if `18082` or `5173` is already busy
- prints the most recent backend or frontend startup log lines if either process fails early

What `run-portable.bat` adds on Windows:

- creates `backend/.venv` automatically if it is missing
- installs backend dependencies on first run
- installs frontend dependencies on first run
- runs a quick local-model readiness check for Ollama, FastEmbed, InsightFace, and CLIP scene analysis
- launches the supported local web app and opens it in your browser

Hot-reload development launch:

```bash
npm run dev
```

Manual two-terminal launch is still available if you need it:

```bash
npm run dev:backend
npm run dev:frontend
```

Default local URLs:

- Frontend: `http://127.0.0.1:5173`
- Backend health: `http://127.0.0.1:18082/api/health`

If either default port is already occupied, the launcher prints the replacement port it selected. If browser auto-open is not available in your environment, the launcher prints the URL to open manually.

### 4. Database and migrations

Local development with `DEBUG=true` auto-creates the schema on startup.

Production-like runs with `DEBUG=false` should apply migrations explicitly:

```bash
cd backend
alembic upgrade head
```

The Docker Compose stack sets `DEBUG=true` by default, which auto-creates the schema on startup.

### Desktop shell

The legacy Electron shell has been archived to `_legacy/`. The supported app is the web frontend + local backend.

## Safe Startup Defaults

- Backend startup now blocks the UI when `/api/health` is degraded, instead of letting the app continue in a half-working state.
- Destructive asset removal is trash-first rather than hard-delete-first.
- Long-running jobs are persisted and recovered after restart instead of existing only in memory.
- Unsupported export formats are rejected explicitly instead of being silently coerced.

## Environment

Important backend environment variables:

- `DATABASE_URL`
- `STORAGE_PATH`
- `DATA_DIR`
- `QDRANT_PATH`
- `DEBUG`
- `ALLOW_REMOTE_ACCESS`
- `DRACO_SECRET_KEY`
- `OLLAMA_BASE_URL`
- `OLLAMA_TIMEOUT`
- `OPENAI_API_KEY`
- `GEMINI_API_KEY`

Reference files:

- repo root: [.env.example](/C:/Users/zackb/Downloads/draco_studio/.env.example)
- backend-local alternative: [backend/.env.example](/C:/Users/zackb/Downloads/draco_studio/backend/.env.example)
- frontend: [frontend/.env.example](/C:/Users/zackb/Downloads/draco_studio/frontend/.env.example)

## Startup And Diagnostics

Useful health and diagnostic endpoints:

- `GET /api/health`
- `GET /api/jobs`
- `GET /api/providers/health`
- `GET /api/providers/configs`

Every backend response now includes `X-Request-ID`. Unhandled server errors also return a `request_id` field in the JSON body.

When troubleshooting a failure:

1. Check `/api/health` first.
2. Copy the `Request ID` shown in the UI error message if one is present.
3. Review backend logs for that request ID or for recovered job warnings after restart.
4. Check `/api/jobs` to confirm whether long-running work was resumed, cancelled, or marked failed after restart.

If the UI shows "Draco could not finish startup", verify:

- the FastAPI backend is running
- the database path is writable
- provider/model startup did not fail
- environment variables like `DRACO_SECRET_KEY`, `STORAGE_PATH`, and `DATABASE_URL` are set correctly

Launcher logs are written to:

- `.logs/launch/backend.log`
- `.logs/launch/frontend.log`

If `npm start` exits early, check those files first.

## Scripts

Useful repo-root commands:

- `npm start` - start the supported local launcher and open the app automatically
- `npm run start:win` - Windows one-click bootstrap and launch flow
- `npm run dev` - start the supported local launcher with backend reload enabled
- `npm run dev:manual` - start backend and frontend in separate child processes without the launcher
- `npm run dev:backend` - run the FastAPI backend with reload
- `npm run dev:frontend` - run the Vite frontend
- `npm run start:backend` - run backend without reload
- `npm run test:backend` - run backend tests
- `npm run test:frontend` - run frontend Vitest suite once
- `npm run build:frontend` - run frontend typecheck and production build
- `npm run lint:frontend` - run frontend linting

## Tests

Backend:

```bash
npm run test:backend
```

Frontend:

```bash
npm run test:frontend
```

Frontend production build:

```bash
npm run build:frontend
```

## Provenance / Third-Party Reuse

Any future vendored code should include:

- license verification
- provenance notes
- bounded ownership
- test coverage around the adopted subsystem
