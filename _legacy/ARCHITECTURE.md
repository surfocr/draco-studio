# Draco Dataset Studio Architecture

## Architecture Goals

- Local-first by default.
- Explainable and non-destructive workflows.
- Provider-swappable core capabilities.
- Project-aware runtime configuration without frontend rewrites.
- Clear path from local desktop mode to hosted/server deployment.

## Top-Level Modules

### Frontend

- React + TypeScript SPA.
- Route-based workspaces for gallery, captions, faces, ranking, search, duplicates, export, benchmark, setup, and settings.
- React Query for backend state.
- Zustand for local UI state.

### Backend

- FastAPI API surface.
- SQLAlchemy async ORM.
- SQLite default local database, Postgres-compatible service boundary for hosted mode later.
- Background jobs via in-process queue today.
- Provider registry for model/service implementations.

### Storage

- Local filesystem for originals, thumbnails, derived files, exports.
- SQLite for metadata and runtime configuration.
- Qdrant/FastEmbed path for embeddings and vector search when enabled.

## Runtime Modes

### Local-only

- SQLite + local storage.
- Ollama/local models preferred.
- No hard cloud dependency.

### Hybrid

- Local providers remain primary where practical.
- Remote APIs are optional and user-key backed.
- Project runtime config chooses where each task runs.

### Hosted / Server

- Same API and provider contracts.
- Requires auth, tenancy, and deployment hardening before being production-ready.

## Provider Model

The backend keeps provider capabilities behind abstract interfaces in `backend/providers/base.py`.

Key capabilities already modeled:

- `CaptionProvider`
- `VisionReasoningProvider`
- `EmbeddingProvider`
- `FaceDetectionProvider`
- `FaceEmbeddingProvider`
- `FaceRecognitionProvider`
- `FaceAttributeProvider`
- `HeadPoseProvider`
- `GazeProvider`
- `ActionUnitProvider`
- `PoseProvider`
- `SceneUnderstandingProvider`
- `DuplicateDetectionProvider`
- `RankingEngine`
- `QualityScorer`
- `ImageEditor`
- `OutpaintingProvider`
- `AngleGenerator`
- `DatasetBalancer`
- `StorageProvider`
- `ExportProvider`
- `TourGuideProvider`

## Runtime Resolution Layer

### New in this pass

`ProjectRuntimeConfig` is now the persistent control plane for per-project runtime behavior.

Stored fields:

- `runtime_mode`
- `task_provider_overrides`
- `task_provider_options`
- `benchmark_preferences`

The runtime resolver service now resolves providers by:

1. explicit request
2. project task override
3. global user default
4. provider rows marked default
5. task-specific fallback order
6. registry availability

## Task Catalog

Current project-aware runtime tasks:

- `caption`
- `ranking_explanation`
- `dataset_coach`
- `embedding`
- `face_detection`
- `scene_understanding`
- `quality`
- `ranking_engine`
- `outpainting`
- `image_editor`

These tasks map to provider types and expose task-specific options. Caption-style tasks currently have the deepest option support, including Ollama-oriented values such as:

- `model`
- `temperature`
- `context_length`
- `max_tokens`
- `timeout`
- `batch_size`
- `concurrency`

## Data Flow

### Ingest

1. Files or directories are submitted.
2. Storage provider saves originals and thumbnails.
3. Asset metadata and hashes are persisted.
4. Background analysis can be queued.

### Analysis

1. Resolve face provider for the project.
2. Resolve embedding provider for the project.
3. Resolve scene provider for the project.
4. Resolve quality scorer for the project.
5. Persist derived metadata and scores.

### Captioning

1. Resolve caption provider for the project and task.
2. Merge project task options with request-level options.
3. Generate caption.
4. Store immutable caption version history.
5. Update active caption pointer non-destructively.

### AI Judge / Ranking Explanations

1. Resolve project-aware reasoning provider via `ranking_explanation`.
2. Merge task options.
3. Ask vision-language provider for structured JSON judgment.
4. Fall back to heuristic scoring if unavailable.

## Provider Config Persistence

### Global provider config

`ProviderConfig` stores:

- secret material like encrypted API keys
- non-secret config like base URLs and model names
- default/enabled flags

### New in this pass

Saved provider config is now re-applied to the live registry on startup and after updates. Previously only encrypted API keys were reliably rehydrated.

## Service Boundaries

Current service boundaries in the backend:

- ingest
- analysis
- captions
- duplicates
- face clustering
- augmentation
- ranking
- coach
- provider config/runtime resolution

Recommended next split for hosted scale:

- ingest service
- analysis workers
- caption/reasoning workers
- vector search service
- face/identity service
- export service

## Frontend Configuration Model

Frontend state should follow this split:

- backend-persisted operational settings:
  - providers
  - runtime mode
  - task defaults
  - benchmark preferences
- client-local presentation state:
  - panel layout
  - zoom
  - sidebar collapse
  - transient filters

The new Settings runtime section now exposes project-aware provider selection and task options instead of forcing all behavior through local-only UI settings.

## External Repo Integration Strategy

- Vendor only stable, bounded code with clean licenses and clear ownership.
- Wrap heavyweight systems as providers instead of importing their architecture wholesale.
- Treat UI-heavy dataset tools mostly as UX references unless their components are narrowly reusable.
- Prefer algorithm or workflow reuse over repo-wide dependency adoption.

See `MODEL_PROVIDER_MATRIX.md` for per-repo decisions.
