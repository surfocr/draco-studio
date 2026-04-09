# Draco Dataset Studio — Build Plan

**Version**: 6.0.0 (Production Rebuild)
**Authored**: 2026-04-04
**Status**: Active development plan — updated as phases complete

---

## Overview

The build proceeds in 7 phases (3A–3G), each shipping a working vertical slice. Each phase builds on the previous. No phase is "done" until its tests pass and the UI reflects the new capability.

---

## Phase 3A — Foundation (Current)

**Goal**: Everything compiles, runs, and stores data. No analysis yet — just structure.

### Backend
- [x] `backend/config.py` — Pydantic Settings with all env vars
- [x] `backend/database.py` — Async SQLAlchemy engine + session + init
- [x] `backend/models/` — All ORM models (Project, Asset, CaptionVersion, FaceCluster, IdentityCluster, RankingSession, RankingComparison, AugmentationJob/Result, ExportJob, ProviderConfig, UserPreferences)
- [x] `backend/providers/base.py` — All abstract provider interfaces + result dataclasses
- [x] `backend/providers/registry.py` — ProviderRegistry singleton
- [x] `backend/providers/storage/local.py` — LocalStorageProvider (full)
- [x] `backend/api/projects.py` — Project CRUD
- [x] `backend/api/assets.py` — Asset CRUD + ingest endpoint
- [x] `backend/api/jobs.py` — Job status + WebSocket progress
- [x] `backend/workers/job_queue.py` — Async job queue (no Redis)
- [x] `backend/services/ingest.py` — File ingest pipeline
- [x] `backend/main.py` — FastAPI app wiring
- [x] `alembic/` — Initial migration
- [x] `requirements.txt` / `.env.example`

### Frontend
- [x] React + Vite + TypeScript scaffold
- [x] Dark theme CSS variables
- [x] AppShell layout (sidebar + header)
- [x] VirtualGrid component
- [x] ImageCard component
- [x] Gallery view (filters, sort, zoom, bulk actions)
- [x] Zustand stores (app, project, asset, job)
- [x] API client hook

### Done when
- `uvicorn backend.main:app` starts without errors
- `vite dev` starts without errors
- Can create a project, drag-drop images, see them appear in the grid
- All DB tables exist via Alembic migration

---

## Phase 3B — Core Analysis Pipeline

**Goal**: Every imported image gets fully analyzed. Face detection, quality scores, embeddings, duplicate detection all populate automatically.

### Backend
- [ ] `backend/providers/face/insightface.py` — Full InsightFace integration (buffalo_l)
  - Face detection, embedding, age/gender/emotion attributes
  - Head pose (yaw/pitch/roll from 5-point landmarks)
  - Face quality score from det_score
  - Lazy model loading, VRAM-aware
- [ ] `backend/providers/embedding/fastembed.py` — CLIP ViT-B/32 via FastEmbed
  - Batch embedding with progress
  - Qdrant upsert + similarity search
  - Collection init on startup
- [ ] `backend/providers/quality/composite.py` — DracoFlow v4 compositor
  - Sharpness: Laplacian variance
  - Resolution score: based on megapixels
  - Face quality: InsightFace det_score
  - Aesthetic: LAION aesthetic predictor (ONNX, optional) or heuristic fallback
  - Brightness/contrast/saturation heuristics
  - Configurable weights per component
  - Full explanation dict
- [ ] `backend/services/duplicate.py` — 4-stage layered detection
  - Stage 1: SHA-256 exact match
  - Stage 2: pHash hamming distance ≤8
  - Stage 3: CLIP embedding cosine ≥0.95
  - Stage 4: Face embedding cosine ≥0.80
  - Returns DuplicateCluster objects
- [ ] `backend/services/analysis.py` — Orchestration
  - Runs all stages in order, partial-failure tolerant
  - Updates Asset record with all results
  - Emits job progress events

### Frontend
- [ ] Score overlay on ImageCard (color-coded composite score)
- [ ] Face bounding box overlay on ImageCard
- [ ] Duplicate cluster indicator badge
- [ ] Analysis progress bar in header

### Done when
- Importing 100 images triggers full analysis pipeline
- All Asset fields populated in DB
- Gallery shows scores + face overlays
- Duplicates flagged automatically

---

## Phase 3C — Caption Workflow

**Goal**: Generate, review, and edit captions for any image using any configured provider.

### Backend
- [ ] `backend/providers/caption/ollama.py` — Full Ollama provider
  - List available models from Ollama API
  - Style-specific prompt templates (natural, concise, danbooru, wd_tags, training_literal)
  - Streaming support
  - Health check
- [ ] `backend/providers/caption/florence2.py` — Florence-2 (HuggingFace)
- [ ] `backend/providers/caption/joycaption.py` — JoyCaption Alpha 2
- [ ] `backend/providers/caption/gemini.py` — Gemini Flash/Pro via API
- [ ] `backend/providers/caption/openai.py` — GPT-4o/mini via API
- [ ] `backend/services/caption.py` — Caption workflow service
  - generate_caption(asset_id, provider, style, db)
  - bulk_generate(asset_ids, provider, style, db) → job_id
  - Version history management
- [ ] `backend/api/captions.py` — Caption CRUD + bulk endpoints

### Frontend
- [ ] Caption editor panel (inline text editing)
- [ ] Provider selector dropdown
- [ ] Style selector (natural/concise/danbooru/wd_tags/training_literal)
- [ ] Caption version history drawer
- [ ] Bulk caption action in Gallery toolbar
- [ ] Caption generation progress overlay

### Done when
- Can select images, choose Ollama model + style, generate captions in bulk
- Caption appears under image in gallery
- Can edit caption inline, versions tracked
- Provider fallback works (Ollama → Gemini if Ollama down)

---

## Phase 3D — Ranking Engine

**Goal**: Rate dataset images via pairwise comparison. AI judge provides explanations.

### Backend
- [ ] `backend/services/ranking.py` — openskill TrueSkill service
  - Maintain mu/sigma per asset
  - rate_pair(winner_id, loser_id) → updates both
  - select_next_pair() → chooses highest-uncertainty pair
  - get_leaderboard(project_id) → sorted by mu - 3*sigma
- [ ] `backend/api/ranking.py` — Ranking session CRUD
- [ ] AI judge: submit pair to configured LLM, get preference + explanation
  - Uses CaptionProvider or dedicated VisionReasoningProvider

### Frontend
- [ ] Ranking view: side-by-side image comparison
  - Keyboard shortcuts: A (left wins), D (right wins), S (skip)
  - Show current mu/sigma for each image
  - Explanation panel (AI judge reasoning)
- [ ] Leaderboard overlay in Gallery (rank badge on each image)
- [ ] Ranking session management (start/pause/resume)

### Done when
- 50 pairwise comparisons produce a stable ranking
- AI judge explains each decision
- Gallery sortable by ranking score

---

## Phase 3E — Dataset Coach

**Goal**: Analyze dataset completeness, gaps, and imbalances. Generate actionable recommendations.

### Backend
- [ ] `backend/services/coach.py` — Analysis engine
  - Shot type distribution analysis
  - Expression/emotion distribution
  - Pose angle coverage (from head_pose_yaw/pitch/roll)
  - Identity cluster balance
  - Background variety score
  - Caption quality analysis (length, keyword coverage)
  - Generates Recommendation objects with priority + action
- [ ] `backend/api/coach.py` — Coach endpoints
  - GET /api/projects/{id}/coach/analysis
  - GET /api/projects/{id}/coach/recommendations
  - POST /api/projects/{id}/coach/ask — freeform question to LLM

### Frontend
- [ ] Coach view with radar chart (shot type coverage)
- [ ] Recommendations list (priority-ordered, with action buttons)
- [ ] Gap visualization: what's missing vs. what's needed
- [ ] "Ask Coach" freeform input (powered by Claude Haiku)

### Done when
- Coach identifies obvious gaps (all closeups, no wide shots; all neutral expressions)
- Recommendations link to Gallery filtered views
- Ask Coach answers reasonable dataset questions

---

## Phase 3F — Editing & Augmentation

**Goal**: Fill dataset gaps by generating new images via outpainting, background replacement, expression editing.

### Backend
- [ ] `backend/providers/export/` — OutpaintingProvider implementations
  - `comfyui.py` — ComfyUI workflow backend
  - `fal_ai.py` — fal.ai Flux Inpainting API
  - `replicate.py` — Replicate API
- [ ] `backend/services/augmentation.py` — Augmentation orchestration
  - Queue outpainting jobs
  - Track source → result relationships
  - Mark augmented assets with augmentation_source_id
- [ ] `backend/api/augmentation.py` — Augmentation endpoints
- [ ] Background removal: rembg integration
- [ ] AngleGenerator: ControlNet + IP-Adapter via ComfyUI

### Frontend
- [ ] Augmentation panel in AssetDetail view
  - Outpaint controls (direction, prompt, padding)
  - Background replace (remove + replace with prompt)
  - Expression edit controls (planned)
- [ ] Augmented badge on generated images
- [ ] Source/result relationship viewer

### Done when
- Can select an image, click "Outpaint → Extend right", get result back
- Augmented images appear in gallery with source link
- Background removal works offline via rembg

---

## Phase 3G — Export & Polish

**Goal**: Export dataset in training-ready formats. Benchmark panel. Guided tours.

### Backend
- [ ] `backend/providers/export/lora_exporter.py` — LoRA training format
  - Images + trigger word captions
  - Configurable repeats per image
  - Metadata sidecar JSON
- [ ] `backend/providers/export/kohya_exporter.py` — Kohya SS format
  - `nn_concept_name/` folder structure
  - `.txt` caption files alongside images
  - `config.toml` generation
- [ ] `backend/providers/export/huggingface_exporter.py` — HuggingFace Datasets
  - Parquet shards + dataset_infos.json
- [ ] `backend/api/export.py` — Export job management
  - POST /api/export — create export job
  - GET /api/export/{id}/download — download ZIP

### Frontend
- [ ] Export view
  - Format selector (LoRA/Kohya/HuggingFace/Raw)
  - Filter by: reviewed only, min score, max duplicates
  - Preview of what will be exported
  - Download button → streams ZIP
- [ ] Benchmark panel: score distributions, provider comparison
- [ ] Guided tour (react-joyride or custom): first-run onboarding
- [ ] Settings view: provider config, API keys, preferences

### Done when
- Can export 200 images as Kohya dataset in < 10 seconds
- Export ZIP contains correct folder structure and caption files
- New user can complete onboarding tour in < 5 minutes

---

## Cross-Cutting Concerns (All Phases)

### Performance
- Thumbnail generation: Pillow, 512px max, WebP format, cached to disk
- Virtual grid: constant DOM node count regardless of dataset size
- Blob URL pool: cache object URLs, revoke on eviction (LRU, max 200)
- VRAM budget manager: serialize GPU tasks, unload idle models after 60s timeout

### Security
- All API keys via Fernet-encrypted ProviderConfig in DB
- No secrets in code or .env files committed to git
- CORS restricted to localhost in production mode

### Testing
- Every provider has a contract test
- Integration tests use real SQLite `:memory:` DB
- Frontend component tests with Vitest + Testing Library

### Observability
- structlog for structured JSON logging
- Every request logged with duration + route
- Job progress via WebSocket + polling fallback
- Error boundary in React catches and displays UI errors

---

## Timeline Estimate

| Phase | Focus | Complexity |
|-------|-------|-----------|
| 3A | Foundation | Medium — lots of boilerplate but well-defined |
| 3B | Core Analysis | High — ML integrations, ONNX, VRAM |
| 3C | Captions | Medium — multiple providers, same pattern |
| 3D | Ranking | Medium — openskill math is simple, UI is the work |
| 3E | Coach | High — analysis heuristics need tuning |
| 3F | Editing | High — ComfyUI workflows are complex |
| 3G | Export | Low-Medium — mostly I/O formatting |

---

*Update this document as phases complete. Mark tasks `[x]` when done, add notes on deviations.*
