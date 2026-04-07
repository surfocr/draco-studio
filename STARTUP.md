# Draco Dataset Studio Quick Start

## Prerequisites

- Python 3.11+
- Node.js 20+
- Optional: Ollama for local captioning and reasoning
- Optional: NVIDIA GPU with CUDA for local AI providers

## Fastest Windows 11 Path

Double-click [run-portable.bat](/C:/Users/zackb/Downloads/draco_studio/run-portable.bat).

It will:

- create `backend/.venv` if needed
- install backend dependencies on first run
- install frontend dependencies on first run
- run a quick local-model readiness check
- start the supported local web app
- open Draco automatically in your browser

You can run the same flow from a terminal:

```bash
npm run start:win
```

## Standard Local Launch

Install dependencies:

```bash
npm install
npm install --prefix frontend
pip install -r backend/requirements-dev.txt
```

Start the app:

```bash
npm start
```

Hot-reload development mode:

```bash
npm run dev
```

## Manual Development Setup

### Backend

```bash
cd backend
python -m venv .venv

# Windows
.venv\Scripts\activate
# macOS/Linux
source .venv/bin/activate

pip install -r requirements.txt
alembic upgrade head
uvicorn main:app --reload --port 18082
```

### Frontend

```bash
cd frontend
npm install
npm run dev
```

Open `http://127.0.0.1:5173`.

## First Run

1. Create a new project.
2. Import images or a whole folder from the Gallery tab.
3. Review duplicates in the Duplicates tab.
4. Run Dataset Coach to get a recommended training subset and next-best additions.
5. Use Ranking to refine the best subset if needed.
6. Export as Kohya SS, LoRA Dataset, or ZIP.

## Local Provider Notes

- Ollama is the main local captioning and reasoning path.
- InsightFace and ONNX Runtime GPU are recommended for face analysis on NVIDIA GPUs.
- If optional heavy dependencies are missing, Draco still starts and reports that the provider is not ready.

## Troubleshooting

- Launcher logs: `.logs/launch/backend.log` and `.logs/launch/frontend.log`
- Health check: `http://127.0.0.1:18082/api/health`
- If startup fails, rerun `run-portable.bat` or `npm start` from a terminal to see the full diagnostics.
