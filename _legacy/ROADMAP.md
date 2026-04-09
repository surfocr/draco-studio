# Draco Dataset Studio Roadmap

## Shipped In This Pass

### Foundation

- Added project-level runtime configuration.
- Added project-aware provider resolution.
- Applied persisted provider config back into the live registry.
- Exposed provider config inspection API.

### Core Service Wiring

- Analysis pipeline now resolves major providers per project.
- Caption generation now honors project runtime defaults and task options.
- AI judging and ranking explanation now honor project runtime defaults and task options.

### UI

- Added Settings support for:
  - runtime mode
  - per-task provider selection
  - per-task caption/reasoning model options

### Correctness / Compatibility

- Added `/api/health` compatibility route.
- Updated tests for project creation status and runtime APIs.

## Milestone 1: Operational Baseline

- Finish migrating remaining operational settings out of `localStorage`.
- Add provider availability caching.
- Add project runtime tests around analysis/caption fallback selection.
- Ensure Alembic migration path is exercised in CI.

## Milestone 2: Dataset Throughput

- Add resumable ingest checkpoints.
- Batch duplicate detection and embedding upserts.
- Add folder watch support.
- Add benchmark result persistence and “choose winner” workflow per project.

## Milestone 3: Face / Identity Stack

- Add stronger identity clustering flow and review UI.
- Introduce optional CompreFace provider wrapper for hosted/hybrid deployments.
- Add explicit face-quality and mislabeled-identity review loops.

## Milestone 4: Search / Ranking Depth

- Add active-learning pair selection with uncertainty visualizations.
- Add persisted AI-vs-human agreement metrics.
- Add project-level ranking engine selection and evaluation history.

## Milestone 5: Editing / Augmentation

- Formalize image editing provider contracts beyond basic outpainting.
- Add ComfyUI workflow presets with provenance.
- Add approval/rejection lifecycle for augmentation outputs with audit trail.

## Milestone 6: Hosted Hardening

- Add authentication and RBAC.
- Add proper remote deployment configuration.
- Add structured audit logs and tenant boundaries.

## Optional / Nice-To-Have

- Tauri packaging evaluation.
- GPU budget manager and model unloading policy.
- More polished benchmark leaderboard and cost/latency comparison views.
- Guided tours backed by `TourGuideProvider`.

## What Remains Optional

- Direct vendoring of third-party UI code.
- Hosted-mode auth stack selection.
- Advanced dataset balancer/angle-generation providers.
- Axolotl-adjacent export helpers for downstream training orchestration.
