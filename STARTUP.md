# Draco Dataset Studio Quick Start

## Prerequisites

- Python 3.11, 3.12, or 3.13
- Node.js 20+
- Optional: Ollama for local captioning and reasoning
- Optional: NVIDIA GPU with CUDA for local AI providers

## Fastest Windows 11 Path

1. Install [Python 3.11+](https://www.python.org/downloads/) — check **"Add python.exe to PATH"**
2. Install [Node.js 20+](https://nodejs.org/) — check **"Add to PATH"**
3. Open a **new** terminal and run:

```cmd
npm run start:win
```

Or just double-click **`run-portable.bat`** in Explorer.

`run-portable.bat` handles everything on first run:

- detects Python 3.11–3.13 via the Windows `py` launcher or `python`
- creates `backend\.venv` and installs Python dependencies
- installs frontend Node.js dependencies
- creates `.env` and `frontend/.env` with a generated `DRACO_SECRET_KEY`
- runs a quick local-model readiness check
- starts backend + frontend and opens Draco in your browser

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

`npm start` uses the `py` launcher first on Windows, then `python`. If Python is still
not found, use `npm run start:win` — `run-portable.bat` handles Python detection and
venv setup automatically.

Hot-reload development mode:

```bash
npm run dev
```

## Manual Development Setup

### Backend

```cmd
cd backend
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
uvicorn main:app --reload --port 18082
```

On macOS/Linux:

```bash
cd backend
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
uvicorn main:app --reload --port 18082
```

> `DEBUG=true` (the default in `.env.example`) auto-creates the database schema on
> startup. No manual `alembic upgrade head` is needed for local development.

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

| Symptom | Fix |
|---|---|
| `'python' is not recognized` | Use `npm run start:win` (handles Python detection), or install Python and check **"Add to PATH"** |
| `'npm' is not recognized` | Install Node.js 20+ from nodejs.org and reopen your terminal |
| Backend port 18082 busy | The launcher picks the next free port automatically and prints it |
| Frontend port 5173 busy | Same — the launcher picks an alternate port |
| `DRACO_SECRET_KEY` warning | Run `npm start` or `run-portable.bat` once to auto-generate a proper secret in `.env` |
| Startup fails silently | Check `.logs/launch/backend.log` and `.logs/launch/frontend.log` |

- Health check: `http://127.0.0.1:18082/api/health`
- If startup fails, rerun `run-portable.bat` or `npm start` from a terminal to see the full diagnostics.
