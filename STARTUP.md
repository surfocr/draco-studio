# Draco Dataset Studio — Quick Start

## Prerequisites

- Python 3.11+
- Node.js 20+
- (Optional) NVIDIA GPU with CUDA for local AI providers
- (Optional) Docker + Docker Compose for containerized setup

## Development Setup (Recommended)

### Backend

```bash
cd backend
python -m venv .venv

# Windows
.venv\Scripts\activate
# macOS/Linux
source .venv/bin/activate

pip install -r requirements.txt

# Initialize the database
alembic upgrade head

# Start the backend
uvicorn main:app --reload --port 18082
```

### Frontend

```bash
cd frontend
npm install
npm run dev
```

Open http://localhost:5173

## Docker Compose

```bash
docker compose up --build
```

- Frontend: http://localhost:5173
- Backend API: http://localhost:18082
- API docs: http://localhost:18082/docs
- Qdrant dashboard: http://localhost:6333/dashboard

## First Run

1. Create a new project and give it a name
2. Import images via drag-and-drop on the Gallery tab
3. Run captioning: go to **Captions** → select a provider → **Generate All**
4. Check duplicates: **Duplicates** tab will auto-group near-identical images
5. Run ranking: **Ranking** tab → **Start Ranking Session** for pairwise comparison
6. Get dataset health: **Dataset Coach** tab shows training readiness grade
7. Export: **Export** tab → select format (Kohya SS / SimpleTuner) → **Download**

## AI Provider Requirements

| Provider | VRAM | Extra Install |
|----------|------|---------------|
| Moondream2 | 4 GB | `pip install moondream` |
| JoyCaption | 12 GB | `pip install transformers accelerate` |
| Qwen2.5-VL 7B | 16 GB | `pip install qwen-vl-utils` |
| LLaVA-NeXT 7B | 16 GB | `pip install transformers` |
| InsightFace | 2 GB | `pip install insightface onnxruntime-gpu` |
| LAION Aesthetic | 4 GB | `pip install open_clip_torch` |
| Real-ESRGAN | 4 GB | `pip install basicsr realesrgan` |
| Ollama | varies | Install from ollama.ai |

Providers gracefully degrade — if a heavy dependency isn't installed, the provider returns a clear error and the app continues normally.

## Environment Variables

Copy `backend/.env.example` to `backend/.env` and fill in any optional API keys.
