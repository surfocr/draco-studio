# Roadmap

Draco Dataset Studio v6 — development status and future plans.

---

## Phase 1 — Audit ✅ COMPLETE

- Inventory of existing code, models, and provider stubs
- Identified gaps between v5 foundation and v6 target architecture
- Documented all missing wiring and incomplete implementations

---

## Phase 2 — Architecture ✅ COMPLETE

- FastAPI + SQLAlchemy async backend with clean router structure
- React + Vite + Zustand frontend with typed API hooks
- Provider registry pattern for caption, quality, embedding, export providers
- Job queue worker system for async heavy tasks
- Database schema: Project, Asset, CaptionVersion, Face, ExportJob, Embedding models

---

## Phase 3 — Core Build ✅ COMPLETE

- Project CRUD and asset ingest pipeline
- Thumbnail generation and file serving
- Caption generation (BLIP2, Florence-2, WD14 tagger)
- Quality scoring (CLIP aesthetic, sharpness, noise)
- Face detection and clustering (InsightFace)
- Ranking arena (ELO-based pairwise comparison)
- Export pipeline: LoRA, Kohya, ZIP formats
- Review workflow: approve / reject / pending states
- Settings panel and provider configuration UI

---

## Phase 4 — Advanced Providers ✅ COMPLETE

- **JoyCaption** — instruction-tuned captioning with style options
- **QwenVL** — multimodal VLM captioning
- **Moondream** — lightweight on-device captioning
- **LLaVA-NeXT** — high-quality open-source VLM captioning
- **LAION Aesthetic Scorer** — perceptual aesthetic quality scoring
- **Real-ESRGAN** — 2x/4x upscaling for low-resolution source material
- **MMPose** — body and hand keypoint detection, pose classification
- **OpenFace** — head pose refinement, action unit detection, gaze estimation

---

## Phase 5 — Search + Smart Features ✅ COMPLETE

- **Semantic search** — CLIP/FastEmbed embedding pipeline, cosine similarity search
- **Smart filters** — filter by score, review state, caption status, augmented flag
- **Auto-sort** — sort gallery by composite score, date, filename, or random
- **AI explanation drawer** — per-asset score breakdown with natural language explanation
- **Score detail panel** — aesthetic, technical, and composite score visualization
- **Dashboard stats** — project-level metrics: counts, coverage, score distributions
- **Embedding pipeline** — batch embed on ingest, incremental re-embed on caption change

---

## Phase 6 — UX Polish ✅ COMPLETE

- **Gallery filters/sort** — live filter bar with multi-criteria combinations
- **Caption bulk edit** — multi-select and apply caption transformations across assets
- **Faces cluster UI** — cluster view with merge, split, and identity labeling
- **Benchmark panel** — side-by-side caption provider A/B comparison, quality rating rollup
- **Duplicates UI** — perceptual hash duplicate detection with merge/delete workflow
- **Settings** — provider enable/disable, scoring weights, export defaults
- **Tooltip system** — contextual help throughout the UI
- **Ranking arena** — swipe-to-rank pairwise review with ELO score update
- **Export with train split** — train/val split configuration, export preview count, validate warnings
- **Augmentation view** — outpaint/fit workflow with aspect ratio selection and plan review

---

## Phase 7 — Optional Future Work

### 7A — Training Integration
- [ ] Direct sd-scripts / SimpleTuner launch from Export tab
- [ ] Training loss curve monitoring
- [ ] Checkpoint viewer

### 7B — Advanced Augmentation
- [ ] ComfyUI integration for inpainting/outpainting
- [ ] IP-Adapter face-preserving expression editing
- [ ] ControlNet-guided angle generation
- [ ] Background replacement pipeline

### 7C — Collaboration / Cloud
- [ ] PostgreSQL backend option
- [ ] Multi-user project sharing
- [ ] Cloud provider integration (Replicate, Modal)
- [ ] Remote backend deployment

### 7D — Performance & Scale
- [ ] Worker pool with Celery/Arq for heavy jobs
- [ ] Incremental re-indexing (only new/changed assets)
- [ ] SQLite WAL mode for concurrent access
- [ ] Thumbnail cache eviction policy

### 7E — Mobile / Packaging
- [ ] Tauri desktop shell
- [ ] Mobile-responsive layout
- [ ] One-click installer
