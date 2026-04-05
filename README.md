# Draco Dataset Studio

A premium, production-grade dataset curation, analysis, augmentation, and export platform for LoRA training, diffusion model fine-tuning, and AI-ready media libraries.

## Features

- **Smart Ingest** — Drag-and-drop import with automatic hash deduplication, thumbnail generation, and metadata extraction
- **Caption Workflow** — Multi-provider captioning (Ollama, Gemini, Florence-2, OpenAI), side-by-side comparison, version history, bulk operations, .txt sidecar export
- **Face Analysis** — InsightFace-powered face detection, clustering, age/gender estimation, head pose (yaw/pitch/roll), dominant expression
- **Duplicate Detection** — 4-layer deduplication: exact hash → pHash → semantic embedding → face embedding similarity
- **Intelligent Ranking** — TrueSkill (openskill) uncertainty-aware pairwise ranking with active learning pair selection; Elo mode available
- **AI Judge** — Per-image explainable scoring across 8 dimensions (technical quality, aesthetic, face clarity, pose, expression, background, uniqueness, training value) with full rationale
- **Dataset Coach** — Automated QA with training readiness grade (A–F), coverage heatmaps, gap detection, and prioritized action plan
- **Augmentation** — PIL-based non-destructive edits (flip, crop, resize); ComfyUI integration for outpainting, background replacement, upscaling
- **Outpainting** — First-class aspect-ratio adaptation with 6 presets + custom; auto-fit subject in frame mode
- **Export** — LoRA training format (Kohya SS / SimpleTuner / OneTrainer compatible), ZIP with sidecars, configurable repeats and trigger words
- **Provider Architecture** — 22 swappable provider interfaces; swap models without frontend changes
- **Local-First** — All core features work fully offline; remote providers (Gemini, OpenAI, Anthropic) are opt-in via user-supplied API keys

## Quick Start

### Requirements
- Python 3.11+
- Node.js 20+
- (Optional) Ollama for local VLM captioning
- (Optional) ComfyUI for AI-powered editing/outpainting

### Install and Run

```bash
# Clone
git clone <repo> draco-studio && cd draco-studio

# Install backend dependencies
pip install -r backend/requirements.txt

# Install frontend dependencies
cd frontend && npm install && cd ..

# Start both servers (backend on :8000, frontend on :5173)
make dev
```

Open http://localhost:5173

### Docker (one command)

```bash
docker compose up
```

Open http://localhost:5173

## Runtime Modes

| Mode | Description |
|------|-------------|
| **Local** | All processing on-device. No cloud required. Privacy-first. |
| **Hybrid** | Local models + optional remote providers (Gemini, OpenAI) for enhanced captioning/reasoning. |
| **Hosted** | Deploy the backend to a remote server; frontend unchanged. |

## Provider Configuration

Set API keys in Settings → Remote Providers, or via environment variables:

```env
GEMINI_API_KEY=your_key_here
OPENAI_API_KEY=your_key_here
ANTHROPIC_API_KEY=your_key_here
REPLICATE_API_KEY=your_key_here
```

For Ollama captioning: ensure Ollama is running on http://localhost:11434 and pull a vision model:
```bash
ollama pull llava:latest
# or
ollama pull moondream
```

## Architecture

See [ARCHITECTURE.md](ARCHITECTURE.md) for full architecture documentation including all provider interfaces, data models, and module boundaries.

See [MODEL_PROVIDER_MATRIX.md](MODEL_PROVIDER_MATRIX.md) for the full model/tool decision matrix.

## Development

```bash
make install    # install all deps
make dev        # start both servers with hot reload
make backend    # start backend only
make frontend   # start frontend only
make migrate    # run database migrations
make lint       # lint backend Python
```

## Roadmap

See [ROADMAP.md](ROADMAP.md) for planned features including MMPose body pose, OpenFace head pose/AUs, LAION aesthetic scorer, and Flux fine-tuning integration.

## License

MIT
