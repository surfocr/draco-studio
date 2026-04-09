# DRACO Dataset Studio v5 — Quick Audit Summary

**For**: Architect reviewing Phase 1 audit
**Date**: 2026-04-04

---

## Critical Findings (10 bullets)

1. **The frontend is a 5,028-line vanilla JS monolith.** No component system, no reactive state, global mutable arrays. Scales to ~300 images before memory collapses (all images stored as base64 in JS heap). This is the #1 rebuild priority.

2. **Two incompatible versions of face-api.js load simultaneously.** Local bundled 0.22.2 (line 9) is overwritten by CDN vladmandic 3.x fork (line 12). The bundled model weights (in `assets/face-api-weights/`) target the 0.22.2 format — they will silently fail to load on the vladmandic version.

3. **API keys are stored plaintext in localStorage, not the encrypted DB.** `DatabaseManager` has correct `safeStorage` + XOR encryption, but the HTML settings tab writes keys directly to `localStorage` and never calls `window.draco.db.setApiKey()`. The encrypted DB system is completely bypassed.

4. **The Orchestrator's browser-dispatch path is unimplemented.** When a task is routed to a `_browser` provider, it returns `{ _executeInRenderer: true, ... }` — but no renderer-side handler reads and executes these descriptors. Cascaded failures silently fall through to API providers.

5. **Several sidecar endpoints are called by `model-manager.js` but don't exist in the server.** `/models/ensure` and `/models/download` are called for model downloads — neither endpoint exists in `draco_server.py`. Model downloads from the Model Manager UI will fail silently.

6. **Export sidecar endpoints (`/export_split`, `/reorder`) are unusable.** They require filesystem `source_dir` paths, but the app stores images as base64 in memory. Project save/load menu items fire IPC events that the HTML never handles. The export story is broken end-to-end for disk-based workflows.

7. **No GPU VRAM budget management.** InsightFace (ONNX) + CLIP (PyTorch) + Florence-2 (PyTorch float16) + DeepFace (TensorFlow) all load into GPU RAM simultaneously. On a 6GB GPU this will OOM. No model eviction or scheduling exists.

8. **`trueskill` dependency is unmaintained (last update 2019) and Python 3.11+ untested.** Arena mode — one of the best features — depends on it. Replace with `openskill` before rebuilding.

9. **Zero tests anywhere in the codebase.** No unit tests (JS or Python), no integration tests, no E2E tests. Any rebuild must establish a test harness from day one.

10. **The overall architecture is sound but needs completion.** The Electron + Python sidecar pattern is correct. The orchestrator fallback chain concept is good. The DracoFlow quality algorithm, TrueSkill Arena, and InsightFace ArcFace integration are genuinely excellent and should be preserved. The rebuild is a front-end migration + plumbing completion, not a ground-up rethink.

---

## What to Keep

- DracoFlow v4 quality algorithm (9-metric, diffusion-informed weights)
- InsightFace ArcFace 512-d face similarity pipeline
- TrueSkill Arena mode (UX is excellent — just swap dependency)
- Python setup wizard with embedded Python auto-download
- Orchestrator fallback chain concept
- Training bucket calculator (Mod-64 — correct)
- Rate limiter in queue.js (token bucket — correct)
- Dark color system (CSS variables — well designed)

## What to Replace

| Replace | With |
|---------|------|
| Vanilla JS monolith | React 18 + TypeScript + Vite |
| Global base64 image state | File path refs + lazy thumbnail loading |
| `trueskill` | `openskill` |
| `deepface` (TF) | ONNX emotion/age classifier |
| `sql.js` + full-DB-on-write | `better-sqlite3` + WAL + batched writes |
| Two face-api.js versions | Single `@vladmandic/face-api` |
| localStorage for API keys | DB `safeStorage` encryption (already built!) |
| `trust_remote_code=True` Florence-2 | LLaVA-1.5 GGUF or CogVLM (no trust needed) |
