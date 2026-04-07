# Draco Dataset Studio Audit

## Current Stack

- Desktop shell: Electron at the repo root.
- Frontend: Vite + React 18 + TypeScript + Zustand + React Query + Tailwind.
- Backend: FastAPI + SQLAlchemy async + SQLite by default.
- ML/runtime pattern: provider registry with local and remote provider implementations.
- Storage: local filesystem, SQLite metadata, optional Qdrant/FastEmbed integration.

## What Was Working

- The repo already had a meaningful FastAPI service layer, typed React frontend, and non-trivial provider abstractions.
- Ollama, FastEmbed, InsightFace, OpenSkill/Elo, export flows, and job queue scaffolding already existed.
- The app had the right product direction: local-first, explainable scoring, dataset workflows, provider-oriented architecture.

## Broken Or Weak Areas Found

### Architecture

- Provider interfaces existed, but runtime selection was still hardcoded in core services.
- Provider configuration persistence was incomplete: saved API keys were reloaded, but saved non-secret provider config was not reliably applied to the live registry.
- Project-specific runtime behavior did not exist, so the platform could not truly support task-specific model/provider selection per dataset.
- Several UI settings lived only in `localStorage`, while operational settings lived in the backend, creating split-brain configuration.
- The backend had many provider stubs but no single project-aware resolution layer.

### Product/UX

- Setup and Settings were global-provider oriented, not project-runtime oriented.
- The product lacked a first-class place to choose per-task providers for captioning, ranking explanation, dataset coaching, embeddings, or face analysis.
- Some existing docs were ahead of the code and described architecture that was only partially wired.

### Quality / Correctness

- Tests and API behavior had drifted:
  - project creation returned `201`, but tests expected `200`
  - health existed at `/health`, while tests expected `/api/health`
- Runtime validation was fragile because the machine did not have a standard Python install and the frontend workspace had no local `node_modules`.

### Performance

- Analysis orchestration was sequential and mostly per-asset, per-stage.
- Hash-based duplicate checks are still effectively linear scans within a project.
- Ollama image calls base64-encode full images per request with no request-side caching.
- Some provider selection fallback paths can still retry expensive availability checks often.

### Security / Ops

- Hosted mode is still not production-ready from a security perspective:
  - no auth or tenancy model
  - loopback-only protection is present, but hosted mode needs a proper security layer
- Provider secrets depend on `DRACO_SECRET_KEY`; without it, encrypted key storage is unavailable.
- Debug-mode CORS is permissive.

## High-Value Missing Infrastructure

- Project runtime profiles and task-level provider defaults.
- Persisted provider benchmark selections per project.
- Stronger worker orchestration and resumable batch checkpoints.
- Hosted-mode auth, RBAC, and audit logging.
- Dataset watch folders and resumable ingest state.
- Formal provenance tracking for any vendored third-party code.

## Changes Implemented In This Pass

- Added `ProjectRuntimeConfig` as a persistent project-level runtime model.
- Added `/api/projects/{project_id}/runtime` endpoints for project runtime mode, task-provider overrides, and task-specific options.
- Added a runtime resolver service so core services can resolve providers by project and task instead of hardcoding names.
- Updated analysis orchestration to resolve:
  - face detection
  - embeddings
  - scene understanding
  - quality scoring
  per project.
- Updated caption generation to support project-aware provider selection and task options.
- Updated AI judge / ranking explanation flows to use project-aware provider resolution and task-specific options.
- Fixed provider config hydration so saved config is applied to the live registry, not just encrypted API keys.
- Added `/api/providers/configs` for provider config visibility.
- Added a legacy `/api/health` alias for compatibility.
- Extended backend tests for runtime config and provider-config visibility.
- Added a Settings UI section for project runtime mode and task-specific provider/model choices.

## Quick Wins Still Available

- Cache provider availability checks for a short TTL.
- Batch or queue pHash duplicate checks instead of doing them inline.
- Persist benchmark panel results and “chosen winner” per project.
- Move remaining operational settings out of `localStorage`.
- Add optimistic frontend mutation handling for runtime settings.

## Major Rewrite Candidates

- Electron root packaging vs frontend/backend workspaces should be normalized into one coherent app build pipeline.
- Worker/job execution should move from in-process queue to a more fault-tolerant background execution model.
- Hosted mode needs a dedicated deployment/auth story instead of being a config toggle.

## Debt List

- Many provider types exist without equal maturity or tests.
- Some comments and docs still imply singleton-style runtime decisions that are now moving to project-aware resolution.
- Validation is partially blocked by environment setup in this workspace.

## Risk List

- Introducing more provider backends without a benchmark-and-provenance discipline will create maintenance drag fast.
- Per-project task options currently fit caption/reasoning tasks best; not every provider type yet supports deep per-project model overrides.
- External repo integration should remain selective; several listed repos are useful only for UX or algorithm inspiration, not direct vendoring.
