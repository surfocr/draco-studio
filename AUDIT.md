# DRACO Dataset Studio v5 — Comprehensive Codebase Audit

**Audit Date**: 2026-04-04
**Auditor**: Senior Full-Stack AI Engineer / ML Systems Architect
**Scope**: Full Phase 1 audit driving production rebuild
**Version Audited**: 5.0.0

---

## 1. DIRECTORY STRUCTURE

```
draco_studio/
├── .gitignore
├── .claude/settings.local.json          ← Claude Code settings (not in git)
├── DRACO_Dataset_Studio_v4.html         ← LEGACY v4 UI (5,000+ line monolith)
├── DRACO_Dataset_Studio_v5.html         ← CURRENT v5 UI (5,028 lines, same pattern)
├── claudedracodatasetthing.pdf          ← Design/spec document
├── electron-builder.yml                 ← Build config (NSIS + Portable targets)
├── package.json                         ← Electron 35.x + sql.js only
├── package-lock.json
│
├── assets/
│   ├── icon.ico
│   └── face-api-weights/                ← Bundled face-api.js model weights (binary)
│       ├── face_landmark_68_model-shard1
│       ├── face_landmark_68_model-weights_manifest.json
│       ├── face_recognition_model-shard1
│       ├── face_recognition_model-shard2
│       ├── face_recognition_model-weights_manifest.json
│       ├── tiny_face_detector_model-shard1
│       └── tiny_face_detector_model-weights_manifest.json
│
├── src/
│   ├── main/
│   │   ├── main.js          (456 lines)   ← Electron entry, IPC registry, CORS
│   │   ├── preload.js       (612 lines)   ← Context bridge + setup wizard injection
│   │   ├── python-manager.js(567 lines)   ← Python env management + sidecar lifecycle
│   │   ├── model-manager.js (166 lines)   ← AI model download/status tracking
│   │   ├── database.js      (299 lines)   ← SQLite via sql.js
│   │   ├── orchestrator.js  (172 lines)   ← Task routing / fallback chains
│   │   └── queue.js         (221 lines)   ← Batch job queue + rate limiting
│   └── renderer/
│       ├── index.html       ← UNUSED — app loads DRACO_Dataset_Studio_v5.html directly
│       └── vendor/
│           ├── tf.min.js                  ← TensorFlow.js 4.x (bundled)
│           ├── blazeface.min.umd.js       ← BlazeFace face detector (bundled)
│           ├── face-api.min.js            ← face-api.js 0.22.2 (bundled, old fork)
│           └── jszip.min.js              ← JSZip 3.10.1 (bundled)
│
└── python/
    ├── draco_server.py     (2,738 lines)  ← FastAPI AI sidecar server
    ├── download_models.py  (87 lines)     ← Model downloader utility
    └── requirements.txt                   ← Python deps (GPU + ML stack)
```

### Module Responsibilities

| Module | Responsibility |
|--------|---------------|
| `main.js` | Electron window + IPC handler registration + CORS policy + file dialogs |
| `preload.js` | Safe renderer bridge (`window.draco`) + setup wizard HTML injection |
| `python-manager.js` | Embedded Python download, venv, pip install, sidecar process lifecycle |
| `model-manager.js` | AI model download status, HuggingFace downloads via sidecar |
| `database.js` | SQLite (sql.js) schema, API key encryption, face embedding cache |
| `orchestrator.js` | Provider fallback chains, cost estimation, task routing |
| `queue.js` | Async batch processing, rate limiting, retries, concurrency control |
| `draco_server.py` | All heavy AI inference (InsightFace, CLIP, Florence-2, aesthetic, etc.) |
| `DRACO_Dataset_Studio_v5.html` | Entire frontend UI + all JavaScript logic (5,028 lines) |

---

## 2. ARCHITECTURE ASSESSMENT

### Frontend Architecture

**Framework**: Vanilla JavaScript — no React, Vue, Svelte, or Angular.
**Pattern**: Single-file HTML monolith (5,028 lines). All CSS, HTML, and JS in one file.
**State management**: Global mutable arrays (`images[]`, `detResults{}`) — no reactive state system.
**Rendering**: Imperative DOM manipulation — `document.getElementById`, `innerHTML` strings.
**Communication**: Dual-path — renderer calls Python sidecar directly via `fetch('http://localhost:18082/...')` AND via `window.draco.analysis.*` IPC bridge.

**Critical Architecture Problem**: The HTML file loads `face-api.min.js` from the local vendor bundle AND simultaneously loads `@vladmandic/face-api` from jsDelivr CDN (line 12). Two different versions of the same library are loaded — the maintained vladmandic fork and the stale 0.22.2 original. This creates a global namespace collision.

```html
<!-- line 9 - local bundle (face-api.js 0.22.2 from 2020) -->
<script src="src/renderer/vendor/face-api.min.js" ...></script>
<!-- line 12 - CDN load of a DIFFERENT fork -->
<script src="https://cdn.jsdelivr.net/npm/@vladmandic/face-api/dist/face-api.js"></script>
```

**State shape**: Each image object carries:
```js
{
  id, url (base64), name, size, cat, selected,
  detResult: { cat, conf, faceRatio, faceBox, landmarks,
               reason, quality, hash, simScore, flags, dupOf }
}
```
All images stored as **base64 in memory** — no disk references for large datasets. This becomes a memory cliff at ~200–300 images.

### Backend Architecture

**Framework**: FastAPI (Python 3.11), single file `draco_server.py` at 2,738 lines.
**Pattern**: Monolithic server — all endpoint logic, helper functions, and model loading in one file.
**Model loading**: Lazy-loaded into global `_models` dict on first request. No model versioning, no GPU memory budgeting between models.
**Port**: 18082 (hardcoded in both JS and Python).
**CORS**: Wildcard `allow_origins=["*"]` — acceptable for a local sidecar but noted.

**Version mismatch in comments**: The server docstring says "DracoFlow v3" and comments say "v4" but the preload.js Setup Wizard and HTML UI refer to "DracoFlow v2". The `/quality-assess` endpoint response includes `"scoring_model": "DracoFlow-v4"` while the HTML computes its own DracoFlow v2 client-side. **Two different scoring algorithms exist in parallel** — the browser-side DracoFlow v2 (6 metrics) and the server-side DracoFlow v4 (9 metrics). The browser version is used for all real-time display; the Python version is only called explicitly by the user.

### Provider Abstraction Layer

**Rating: Partial / Incomplete**

`orchestrator.js` defines a fallback chain system:
```js
const DEFAULT_CHAINS = {
  face_detect:  ['insightface_local', 'blazeface_browser'],
  caption:      ['florence2_local', 'ollama_local', 'gemini_api', ...],
  ...
}
```

**Problems**:
1. The actual browser-side tasks (`_executeInRenderer: true`) are returned as descriptor objects, not executed. The renderer must handle them separately — but there is no corresponding renderer-side dispatcher that reads these descriptors. The Orchestrator is partially implemented.
2. The `_getEndpoint()` map references `/clip-embed` but the server exposes `/embed` (via fastembed) and `/clip-embed` (via transformers CLIP) — naming is inconsistent.
3. `queue.js` uses `orchestrator.chains[job.type][0]` for concurrency decisions without accounting for provider failover — if the first provider fails, the concurrency limit logic is wrong for the fallback provider.
4. The orchestrator's `_isAvailable()` always returns `true` for `ollama_local` without actually checking if Ollama is running (line 107: `return true`).

### Worker / Job Queue

`queue.js` implements a token-bucket rate limiter + concurrency limiter for batch jobs. It is well-structured. **Issues**:
- `_processLoop()` uses a `while(true)` spin loop with 200ms `setTimeout` — this is wasteful; it should use event-driven wake-up.
- When `submit()` is called a second time, it resets `this.jobs` and `this.stats` but does not cancel in-flight `this.active` promises from the previous submission. Race condition risk.
- `_canRun()` determines the provider from `chain[0]` rather than the actual provider that will be used. If `insightface_local` is unavailable and `blazeface_browser` is used, the concurrency check is still evaluated against `insightface_local`'s limit.

### Database / Storage

- **Technology**: `sql.js` (SQLite compiled to WebAssembly, runs in Node.js main process)
- **Persistence**: Entire DB exported to disk as binary on every `run()` call (line 118: `this._save()`)
- **Schema**: 7 tables (projects, images, face_embeddings, api_keys, api_usage, model_status, settings)
- **API key encryption**: Electron `safeStorage` with XOR fallback using hardcoded key `'DracoStudioV5'` (database.js line 215). The XOR fallback is security theater — it provides trivial obfuscation, not encryption.
- **Critical**: The DB is written to disk on every single INSERT/UPDATE. For a batch of 500 images, this means 500 full-DB serializations. This will be extremely slow for large datasets.
- **Missing**: No migration versioning. `_migrate()` uses `CREATE TABLE IF NOT EXISTS` — schema evolution (adding columns) is not handled.

### Vector Store

**None**. No dedicated vector store (Qdrant, Chroma, FAISS, etc.) is used. CLIP embeddings are:
1. Computed by the Python sidecar
2. Returned to the renderer as JSON arrays
3. Stored temporarily in `localStorage` (with `btoa()` encoding)

This means the 768-d float arrays for all images are in localStorage, which has a 5–10MB browser limit. For a dataset of 500 images, 500 × 768 × 4 bytes = ~1.5MB — it barely fits, but clustering requires sending all embeddings back to Python each time.

### Model Loading / Management

- **Lazy loading**: Good pattern — models load on first use
- **No VRAM budgeting**: InsightFace (ONNX GPU), CLIP (PyTorch GPU), Florence-2 (PyTorch GPU), DeepFace all load into GPU memory simultaneously once triggered. On a 6GB GPU, this will OOM.
- **No model offloading**: Once loaded, models stay in `_models` dict forever. No cache eviction.
- **Aesthetic model path**: Hardcoded to `python/models/aesthetic_v2.onnx` relative to `__file__` (draco_server.py line 185). If the sidecar is started from a different CWD, this fails.
- **Florence-2 uses `trust_remote_code=True`**: Security risk for a production app shipping to end users.

---

## 3. DEPENDENCY AUDIT

### Node.js / Electron Dependencies

| Package | Version | Status | Action |
|---------|---------|--------|--------|
| `electron` | ^35.7.5 | Current (stable 35.x is recent) | **Keep** — latest stable |
| `electron-builder` | ^26.5.0 | Current | **Keep** |
| `sql.js` | ^1.11.0 | Current (SQLite 3.45 WASM) | **Evaluate** — consider `better-sqlite3` for main process; sql.js is designed for browser use, not Node |

### Frontend Vendor Libraries (bundled in `src/renderer/vendor/`)

| Library | Bundled Version | Current | Status | Action |
|---------|----------------|---------|--------|--------|
| `@tensorflow/tfjs` | 4.17.0 | 4.22.x | Maintained | **Upgrade** — 4.17 → 4.22+ |
| `@tensorflow-models/blazeface` | 0.1.0 | 0.1.0 (abandoned) | Stale (last update 2021) | **Replace** — use MediaPipe FaceLandmarker or InsightFace via sidecar |
| `face-api.js` | 0.22.2 | Abandoned (last: 2020) | **Dead** | **Replace** — vladmandic fork or drop in favor of InsightFace sidecar |
| `@vladmandic/face-api` | CDN latest | 3.x | Maintained fork | Keep if face-api.js is needed, but consolidate — currently two versions load simultaneously |
| `jszip` | 3.10.1 | 3.10.1 | Maintained | **Keep** |

### Python Dependencies

| Package | Min Version | Current Latest | Status | Notes |
|---------|-------------|---------------|--------|-------|
| `fastapi` | ≥0.115.0 | 0.115.x | Current | Keep |
| `uvicorn[standard]` | ≥0.32.0 | 0.34.x | Current | Keep |
| `numpy` | ≥1.26.0 | 2.2.x | Current | Note: numpy 2.x breaking changes — pin carefully |
| `opencv-python` | ≥4.10.0 | 4.10.x | Current | Keep |
| `Pillow` | ≥10.4.0 | 11.x | Current | Upgrade to 11.x |
| `insightface` | ≥0.7.3 | 0.7.3 | **Stale** (last PyPI: 2023) | Maintained on GitHub — pin to GitHub main or keep 0.7.3 |
| `onnxruntime-gpu` | ≥1.19.0 | 1.20.x | Current | Keep — GPU acceleration for InsightFace |
| `torch` | ≥2.4.0 | 2.6.x | Current | **Upgrade** — 2.4 → 2.6+ for Flash Attention, torch.compile |
| `torchvision` | ≥0.19.0 | 0.21.x | Current | Upgrade with torch |
| `transformers` | ≥4.46.0 | 4.50.x | Current | Keep, upgrade |
| `huggingface-hub` | ≥0.26.0 | 0.30.x | Current | Keep, upgrade |
| `timm` | ≥1.0.0 | 1.0.x | Current | Keep |
| `einops` | ≥0.8.0 | 0.8.x | Current | Keep |
| `pyiqa` | ≥0.1.12 | 0.1.13 | Current | Keep |
| `rembg` | ≥2.0.59 | 2.0.61 | Current | Keep |
| `fastembed` | ≥0.4.0 | 0.5.x | Current | Keep — ONNX CLIP is a good pattern |
| `scikit-learn` | ≥1.4.0 | 1.6.x | Current | Keep |
| `hdbscan` | ≥0.8.38 | 0.8.39 | Maintained | Keep |
| `umap-learn` | ≥0.5.6 | 0.5.7 | Maintained | Keep |
| `trueskill` | ≥0.4.5 | 0.4.5 | **Unmaintained** (last: 2019) | **Replace** — use `openskill` (actively maintained, same Bayesian ranking) |
| `deepface` | ≥0.0.90 | 0.0.93 | Maintained | Keep — but emotion/age analysis should be optional |

**High-risk dependency**: `trueskill` 0.4.5 — last updated 2019, Python 3.11+ compatibility is not guaranteed. Switch to `openskill`.

**Size concern**: Full install requires downloading:
- PyTorch 2.6 GPU: ~2.7GB
- torchvision: ~400MB
- transformers + Florence-2: ~1.3GB
- CLIP model: ~890MB
- InsightFace buffalo_l: ~330MB
- Total first-run: **~7GB+ download**

No lazy/optional installs — everything installs upfront.

---

## 4. FEATURE COMPLETENESS

### Dataset Ingest / Drag-Drop Import
**Status: Implemented, functional**
- Drag-drop via `#dz` drop zone
- Browse via `<input type="file" multiple>`
- Folder open via Electron IPC (`fs:open-folder`)
- 8 concurrent `FileReader` ops for batch loading
- Supports: jpg, jpeg, png, webp, gif, bmp, tiff, heic, avif
- **Gap**: No recursive folder scanning (only reads top-level directory, line 213 in main.js)
- **Gap**: HEIC/AVIF formats accepted by dialog but browser `FileReader` cannot decode them without native support

### Caption Generation
**Status: Implemented (local), Partial (API)**
- Florence-2 local captioning via Python sidecar — **functional**
- Ollama / LM Studio local integration — **functional**
- Claude, GPT-4o, Gemini, Groq, OpenRouter API — UI exists but actual API calls are in the HTML as direct `fetch()` to external endpoints — **functional but API keys stored in localStorage (plaintext), not the encrypted DB**
- Two-description system (identity + scene) — **implemented**
- Trigger word prefix — **implemented**
- Caption mode (minimal/detailed/structured) — **implemented in Python sidecar**
- **Gap**: Caption batch via Python sidecar uses sequential loop in `caption_batch()` — no actual batching to Florence-2
- **Gap**: No vision-language model with structured output (system prompts, JSON schema) — captions are freeform

### Caption Editing Workflow
**Status: Partially implemented**
- Manual textarea editing — **functional**
- AI scoring of captions (length, density, trigger word check) — **functional in Python sidecar**
- Download captions as ZIP — **functional**
- **Gap**: No per-image caption history / version tracking
- **Gap**: No inline diff view between AI caption and manual edit
- **Gap**: Caption scoring is exposed in the sidecar but the UI hook to call it is unclear — the `analysis.scoreCaption()` IPC bridge exists but the HTML tab does not visibly wire it to a button

### Face Detection / Clustering / Recognition
**Status: Implemented (multi-layer), functional with caveats**
- BlazeFace (TF.js, browser-side) — real-time detection during import
- InsightFace ArcFace 512-d (Python sidecar) — high-accuracy embeddings
- Agglomerative hierarchical clustering (`/cluster-faces`) — **implemented**
- DBSCAN face clustering (`/face_cluster`) — **implemented**
- Face similarity score vs. reference image (128-d face-api.js) — **implemented**
- **Gap**: The face clustering UI is not wired to a dedicated workflow panel. Cluster results exist in the sidecar but there is no UI to browse by identity cluster
- **Gap**: face-api.js (browser) and InsightFace (sidecar) operate as parallel systems — their results are never reconciled

### Emotion / Expression / Head Pose Analysis
**Status: Partial**
- Head pose (yaw/pitch/roll) via InsightFace 5-point landmarks — **implemented, functional**
- Emotion analysis via DeepFace — **sidecar endpoint exists** (`/face_attrs`) but is not called from the UI
- Age/gender via InsightFace — **implemented in batch-faces responses**
- **Gap**: No dedicated expression diversity panel
- **Gap**: DeepFace is loaded but the UI never triggers it

### Body Pose Analysis
**Status: Not implemented**
- No pose estimation library (MediaPipe Pose, OpenPose, etc.)
- Shot type (close-up/mid/full) is a proxy for body pose via face ratio — this is approximate and fails for images without faces

### Scene / Background Understanding
**Status: Partial**
- `_analyze_background()` in sidecar classifies backgrounds as neutral/simple/moderate/busy based on border color variance — **functional but primitive**
- Background removal via BRIA RMBG-2.0 (`/remove-background`) — **functional**
- **Gap**: No semantic scene classification (indoor/outdoor, studio/natural, etc.)
- **Gap**: Background analysis results are buried in `/quality-assess` response but not surfaced as a filter or warning in the UI

### Semantic Search / Duplicate Detection
**Status: Partial**
- pHash duplicate detection (browser-side, 64-bit Hamming ≤9) — **functional**
- pHash duplicate detection (sidecar, DCT-based 16x16 pHash with 64-bit output) — **functional** (slightly different algorithm than browser-side)
- SSCD advanced duplicate detection (`/find-duplicates-advanced`) via `torch.hub` — **wired in IPC but the HTML doesn't call it from the UI**
- CLIP semantic search (`/embed_text`) — **sidecar endpoint functional** but no search UI panel exists
- **Gap**: Two different pHash implementations (browser 8×8 average hash vs. sidecar DCT 16×16) — results will not agree
- **Gap**: No semantic text search UI
- **Gap**: SSCD is loaded via `torch.hub` (requires internet on first run, not bundled)

### Manual Ranking (Pairwise / Tournament)
**Status: Implemented**
- Arena mode with pairwise comparison — **functional**
- Keyboard shortcuts (J/K/L for left/draw/right, Z for undo) — **functional**
- Session persistence via localStorage — **functional**
- Confidence tracking (% pairs decided) — **functional**
- **Gap**: No persistent leaderboard across sessions (ratings reset on clear)
- **Gap**: No way to seed Arena from quality scores (start near the top, not random)

### AI-Assisted Ranking
**Status: Partial**
- TrueSkill Bayesian ranking updates via sidecar — **functional**
- AI Deep Review (Ollama/LM Studio vision analysis, 3 recursive passes) — **functional**
- AI Quality Score (45% AI + 55% DracoFlow v2 composite) — **functional**
- **Gap**: AI-assisted ranking requires a local vision model (Ollama) — no fallback to API vision models for ranking

### Explainable Scoring
**Status: Partial**
- Lightbox shows per-metric breakdown (sharpness/pose/contrast/brightness/center/saturation) — **functional**
- DracoFlow composite tooltip in Analytics tab — **functional**
- **Gap**: No explanation for why an image was flagged by AI Deep Review
- **Gap**: No visual heatmap showing which regions contributed to the quality score

### Dataset Coach / QA Mode
**Status: Partial**
- Analytics tab with Health Score, Issues panel, AI Deep Review — **functional**
- Shot distribution histogram — **functional**
- Per-model dataset recommendations — **implemented in sidecar** (`MODEL_DATASET_RECS`)
- DracoFlow v3/v4 dataset analysis report — **functional**
- **Gap**: No conversational "coach" interface — recommendations are one-shot static text
- **Gap**: The Dataset Analysis Report (`/analyze-dataset`) is wired in IPC but not clearly triggered from the Analytics UI — it appears to be accessible from the sidebar "Dataset" button only

### Image Editing / Augmentation
**Status: Minimal**
- Horizontal flip + color jitter via sidecar (`/augment`) — **implemented in sidecar**
- **Gap**: No crop/rotation/brightness adjustment tool in UI
- **Gap**: `/augment` is wired in IPC but not surfaced with a UI button
- **Gap**: No outpainting / aspect ratio expansion

### Outpainting / Aspect Ratio Adaptation
**Status: Not implemented**
- The IPC bridge has references to `wavespeed_api` and `fal_api` in cost tables
- No outpainting endpoint exists in the sidecar
- No outpainting UI panel

### Export Workflows
**Status: Partial**
- ZIP download of categorized images + captions — **functional**
- Export modes: flat/clustered/ranked/arena — **defined in sidecar** (`/export_split`, `/reorder`)
- Training config display (preset, resolution, bucket mode) — **functional**
- **Gap**: `/export_split` and `/reorder` sidecar endpoints require `source_dir` and `output_dir` (filesystem paths) — but the app stores images as base64 in memory, not on disk. These endpoints cannot be called unless images were loaded from disk paths.
- **Gap**: No Electron file-save dialog wired to the export split/reorder flow
- **Gap**: Export ZIP creates a blob download in browser — does not use Electron's native `showSaveDialog` for large datasets

### Guided Tours / Tooltips / Onboarding
**Status: Implemented**
- 25+ context-sensitive TIPS system — **functional**
- Setup wizard (5-step: Python → venv → packages → GPU → server start) — **functional**
- Keyboard shortcuts help modal — **functional**
- **Gap**: No interactive guided tour (step-by-step walkthrough for new users)
- **Gap**: Setup wizard is injected by preload.js as raw HTML string — fragile

### Provider Selection UI
**Status: Implemented**
- Settings tab with API key inputs for Claude, GPT, Gemini, Groq, OpenRouter — **functional**
- Ollama/LM Studio local backend toggle — **functional**
- **Gap**: No provider health check UI (shows if each API key is valid)
- **Gap**: API keys stored in `localStorage` (plaintext) in the HTML — the encrypted DB system in `database.js` is NOT used by the HTML frontend. The `window.draco.db.setApiKey()` bridge exists but the HTML never calls it.

### Benchmark / Bakeoff Panel
**Status: Not implemented**
- No panel to compare multiple AI providers head-to-head
- No side-by-side caption comparison
- No quality score comparison across models

---

## 5. BROKEN OR PROBLEMATIC CODE

### Critical Bugs

**BUG-001** — `src/renderer/vendor/face-api.min.js` AND `@vladmandic/face-api` CDN both loaded (HTML lines 9, 12)
Two different versions of face-api.js overwrite the same `faceapi` global. The local 0.22.2 bundle loads, then the CDN vladmandic fork replaces it. The face-api.js weights in `assets/face-api-weights/` are for the original 0.22.2 API and may be incompatible with the vladmandic 3.x format. The weights manifest format changed between versions.

**BUG-002** — `src/renderer/index.html` is dead code
The app loads `DRACO_Dataset_Studio_v5.html` directly (main.js line 51). `src/renderer/index.html` is never loaded. It clutters the build.

**BUG-003** — API keys stored in `localStorage` not encrypted DB
HTML settings tab stores Claude/GPT/Gemini keys directly in `localStorage`. The `DatabaseManager._encrypt()` system with OS `safeStorage` is completely bypassed. Keys are plaintext in Chromium's localStorage storage.

**BUG-004** — `PythonManager.getStatus()` stale cache
`python-manager.js` line 454: `if (this._statusCache === undefined)` — the Python detection result is cached on first call and never updated. If Python is installed after the first status check, it won't be detected until restart.

**BUG-005** — `queue.js` submit() race condition (line 44-45)
`this.stats` is reset synchronously but `this.active` Map is not cleared. If `_processLoop` is still running from a previous submission, the new stats will be corrupted by completions from old jobs.

**BUG-006** — `orchestrator.js` ollama_local availability always true (line 107)
```js
if (provider === 'ollama_local') return true; // Checked by renderer
```
This means the orchestrator will always choose `ollama_local` for caption tasks even when Ollama is not running, and the "fallthrough on failure" will eventually reach API providers — but only after a failed HTTP request timeout, degrading UX.

**BUG-007** — Export sidecar endpoints unusable with base64 images
`/export_split` and `/reorder` endpoints in `draco_server.py` expect filesystem `source_dir` and `output_dir` paths. The frontend only has base64-encoded image data in memory. These endpoints can only work if the user opened images from disk and those paths were tracked — which the current state model (`images[i].url` = base64 data URL) does not support.

**BUG-008** — `python-manager.js` redirect handling leaks file descriptor
`_downloadFile()` at line 484: on redirect, `file.close()` is called but the file is reopened with `new createWriteStream(dest)` in the same scope. If the redirect handler also throws, the new file stream is never closed. Minor resource leak.

**BUG-009** — Aesthetic model path hardcoded relative to `__file__`
`draco_server.py` line 185: `Path(__file__).parent / "models" / "aesthetic_v2.onnx"`. When bundled in Electron's ASAR, `__file__` resolves inside the ASAR archive. The ONNX model must exist there or the aesthetic scoring silently fails (returns `None`).

**BUG-010** — pHash algorithm mismatch between browser and sidecar
Browser (HTML line ~2100): 8×8 average hash → 64-bit integer via threshold.
Sidecar (`_compute_phash()`): DCT-based 16×16 pHash → 64-char binary string.
Hamming distance in browser is calculated on integers; sidecar returns binary string. These are incompatible — cross-system duplicate detection will fail.

### Anti-Patterns

**AP-001** — XOR "encryption" with hardcoded key (`database.js` line 215)
```js
const key = 'DracoStudioV5';
```
This is not encryption. Any user who opens the SQLite file can trivially decode all API keys.

**AP-002** — `db._save()` called on every write
Serializing the entire SQLite database to disk on every `INSERT` or `UPDATE` is O(n) where n is DB size. At 500 images with embeddings, this creates serious latency.

**AP-003** — All images stored as base64 in memory
For 500 images at 2MB each, the renderer holds ~1GB of base64 strings in JavaScript heap. The browser will be killed by the OS on most machines.

**AP-004** — `while(true)` spin loop in `queue.js` `_processLoop()` (line 85)
The 200ms polling interval wastes CPU when queue is idle. Should use `Promise` resolution triggers.

**AP-005** — `trust_remote_code=True` in Florence-2 loading (`draco_server.py` line 144)
This allows arbitrary Python execution from the HuggingFace model repository. Acceptable in a dev context; not acceptable in production software shipped to end users.

**AP-006** — O(n²) agglomerative clustering in pure Python (`draco_server.py` line 505–527)
The `cluster-faces` endpoint implements average-linkage hierarchical clustering with a Python `for` loop over all pairs. For 500 images, this is 500×500/2 = 125,000 iterations per pass. This will block the event loop for seconds. Should use `scipy.cluster.hierarchy` or `sklearn.cluster.AgglomerativeClustering`.

**AP-007** — Setup wizard HTML injected as raw string by preload.js
`preload.js` line 146: `overlay.innerHTML = \`...\`` with 300+ lines of HTML and CSS as a template literal. This is fragile, unstyled consistently with the main app, and impossible to test independently.

**AP-008** — `DRACO_Dataset_Studio_v4.html` still ships in the build
`electron-builder.yml` includes both `DRACO_Dataset_Studio_v5.html` and `DRACO_Dataset_Studio_v4.html`. The v4 file (5,000+ lines) adds dead weight to every build and installer.

### Dead Code

- `src/renderer/index.html` — never loaded
- `DRACO_Dataset_Studio_v4.html` — superseded by v5
- `ipcMain.handle('app:read-v4-html')` in `main.js` line 366 — loads v5 HTML and falls back to v4; this IPC handler is never called from the renderer
- `model-manager.js` `downloadModel()` for `installType: 'pip'` calls `/models/ensure` — this endpoint does not exist in `draco_server.py`
- `model-manager.js` `downloadModel()` for `installType: 'huggingface'` calls `/models/download` — this endpoint does not exist in `draco_server.py`. Model downloads will silently fail.

### Missing Error Handling

- `draco_server.py`: `get_insightface()` will throw an `ImportError` if insightface is not installed — the exception propagates as a 500 error with no user-friendly message
- `python-manager.js` `_extractZip()`: Uses PowerShell `Expand-Archive` — if PowerShell execution policy blocks the script, it fails silently (error goes into `stderr` which is only logged if `streamLogs=true`)
- `queue.js`: `_executeJob()` calls `orchestrator.route()` — if all providers fail, the error message is `"No available provider for task: X"` with no user-visible notification

---

## 6. UX ASSESSMENT

### UI Framework
**Rating: Functional but dated**
Pure vanilla JS DOM manipulation in a 5,028-line HTML file. No component system, no templating, no reactive state. Feature additions require manual DOM wiring throughout. The codebase has grown beyond what is maintainable in this paradigm.

### Dark Mode
**Status: Yes — dark-only**
The entire UI uses a consistent dark color system via CSS variables:
- `--bg: #060810` (near-black)
- `--cy: #00DCFF` (cyan accent)
- `--gn: #00FF9D`, `--or: #FFB830`, `--rd: #FF3E50`, `--pu: #B44FFF`

No light mode exists. This is appropriate for a power-user ML tool.

### Virtualized Grid
**Status: Partial — CSS-only optimization, no true virtualization**
`content-visibility: auto` is applied to image cards, which tells the browser to skip rendering off-screen elements. This is CSS-level optimization, not JavaScript virtualization. For 1,000+ images, all DOM nodes are still created and maintained in memory. Scrolling will degrade significantly beyond ~300 images. A true virtual scroller (e.g., virtual-scroller or TanStack Virtual) is needed.

### Loading States / Progress Bars
**Status: Implemented for core flows**
- File import progress overlay (`#load-overlay`) — **functional**
- Detection progress bar (`#dpb`) — **functional**
- Python download progress (`#dprog`) — **functional**
- Per-job batch queue progress — **functional**
- **Gap**: No per-image loading spinner while analysis is running
- **Gap**: Python sidecar startup (up to 90s) shows no progress breakdown (which model is loading)

### Navigation
**Status: Functional, power-user oriented**
- 8-tab navigation at top of header
- Step wizard (`#step-bar`) for guided workflow
- Keyboard shortcuts for tab switching (Alt+1-7)
- **Gap**: Step wizard and tab bar are redundant — two navigation systems for the same workflow
- **Gap**: No breadcrumb or visual indication of where in the workflow the user is
- **Gap**: Tabs are labeled with 2–7 letter abbreviations (no icons) — not intuitive for new users

### Accessibility
**Not audited** — but visual inspection suggests no ARIA labels, no keyboard focus management, no screen reader support.

---

## 7. IDENTIFIED GAPS

### Completely Missing Features

1. **Body pose estimation** — No MediaPipe Pose, OpenPose, or ControlNet annotation. Shot type is only approximated via face ratio.
2. **Semantic text search** — `/embed_text` endpoint exists but no UI panel to search images by text query.
3. **Outpainting / aspect ratio expansion** — Referenced in orchestrator cost tables (`wavespeed_api`, `fal_api`) but no implementation.
4. **Provider benchmark panel** — No A/B comparison of captioning providers.
5. **Image deduplication across projects** — No cross-project duplicate checking.
6. **Recursive folder import** — Only scans top-level directory.
7. **HEIC/AVIF decoding** — File dialog accepts them but browser `FileReader` + `<img>` cannot display them without native decoder.
8. **Project save/load** — Menu item exists (`Save Project` / `Load Project`), IPC events fire, but the HTML never handles `menu:save-project` or `project:load` events with actual serialization code.
9. **Conversation-style Dataset Coach** — Recommendations are one-shot static text from `/analyze-dataset`.

### Partially Implemented / Broken

1. **Export workflows** — Sidecar endpoints exist but require filesystem paths that aren't tracked.
2. **SSCD advanced duplicate detection** — Endpoint works but UI doesn't expose it.
3. **Face identity clustering UI** — Computation works but no UI to browse clusters.
4. **Augmentation UI** — Endpoint works but no UI button.
5. **DeepFace emotion analysis** — Loaded in sidecar but never called from UI.
6. **Model Manager** — `downloadModel()` in `model-manager.js` calls endpoints that don't exist in the sidecar.
7. **Orchestrator browser-side dispatch** — Returns `_executeInRenderer: true` descriptors but renderer has no handler for them.
8. **Caption scoring** — IPC bridge exists, sidecar endpoint works, but UI doesn't call it.

### Well-Done, Keep As-Is

1. **DracoFlow quality algorithm** — The 9-metric composite scoring (v4 in sidecar) is well-thought-out with diffusion-informed weights.
2. **TrueSkill Arena mode** — Keyboard-driven, smooth UX, solid ranking theory.
3. **Python setup wizard** — Automated embedded Python download + venv + pip is excellent for a no-admin Windows workflow.
4. **InsightFace ArcFace integration** — Best-in-class face similarity (99.83% LFW). Well integrated.
5. **Training bucket calculator** — Correct Mod-64 bucketing implementation.
6. **Rate limiter in queue.js** — Token bucket algorithm is correct and well-implemented.
7. **Orchestrator fallback chain pattern** — Good architecture concept, needs completion.
8. **CORS policy in main.js** — Correct, minimal allowlist.
9. **safeStorage API key encryption** — Correct when safeStorage is available.

---

## 8. RISK AREAS

### Hardest to Rebuild Cleanly

1. **State management in 5,028-line HTML monolith** — The entire application state is global mutable arrays. Migrating to a React/Vue component tree requires threading state through dozens of event handlers. This is the highest-effort rebuild item.

2. **Browser ↔ Python ↔ Electron three-way data flow** — The app has three execution contexts (renderer, main process, Python sidecar) with two IPC boundaries. Some calls go renderer → fetch → sidecar directly; others go renderer → IPC → main → HTTP → sidecar. Standardizing this is non-trivial.

3. **Image memory model** — The entire dataset as base64 in JS heap is a fundamental scaling problem. Switching to file-path references requires tracking native paths through all the analysis pipelines and refactoring every operation that currently reads from `img.url`.

4. **GPU memory management across models** — On a 6GB GPU, loading InsightFace + CLIP + Florence-2 + DeepFace simultaneously will OOM. Need explicit model routing with unload/load.

### Dependencies Most Likely to Cause Issues

1. **`trueskill` 0.4.5** — Python 3.11+ untested, unmaintained since 2019. Arena mode depends on it.
2. **`insightface` 0.7.3** — Last PyPI release 2023, ONNX Runtime 1.19+ may have API changes.
3. **`face-api.js` 0.22.2 + weights** — The bundled weights use the original 0.22.2 weight format. The CDN-loaded vladmandic fork uses a different format. Weights will likely fail to load for one of the two libraries.
4. **`hdbscan` 0.8.38** — Requires `cython` compilation on some platforms; may fail on Python 3.12+. Consider `fast-hdbscan` instead.
5. **`deepface` ≥0.0.90** — Pulls in TensorFlow as a dependency, adding ~1.5GB to the install.

### ML Models Poorly Integrated

1. **Aesthetic model** — Path hardcoded relative to `__file__`; ASAR packaging will break it. The `download_models.py` script downloads to `python/models/` but the sidecar looks there only when running from source. In production (ASAR), this path doesn't exist.

2. **SSCD** — Loaded via `torch.hub.load()` which fetches from GitHub at runtime. No offline support. The URL is not pinned to a specific commit. Will break if the repository structure changes.

3. **Florence-2 `trust_remote_code=True`** — This executes arbitrary Python from HuggingFace. Acceptable in dev but a security risk in a distributed product. Should switch to a non-trust-required captioning model (LLaVA-1.5, CogVLM, or a local GGUF via llama.cpp).

4. **TOPIQ via `pyiqa`** — `pyiqa` downloads model weights from their own CDN on first use. No offline fallback. First-run latency is high.

5. **DeepFace** — Pulls TensorFlow (not torch) as a dependency, creating a mixed PyTorch + TF environment. This doubles GPU init overhead and can cause CUDA context conflicts.

---

## 9. SUMMARY TABLE

| Area | Score | Notes |
|------|-------|-------|
| Architecture | 5/10 | Good concepts, poor execution — monolith HTML, no reactive state |
| Frontend framework | 3/10 | Vanilla JS monolith — unscalable |
| Backend API | 7/10 | FastAPI is correct choice; monolith file needs splitting |
| Provider abstraction | 4/10 | Partially designed, orchestrator browser dispatch is unimplemented |
| Database | 4/10 | sql.js + full DB serialization on every write = performance cliff |
| AI model integration | 6/10 | Good model choices, poor VRAM management, some path bugs |
| Feature completeness | 6/10 | Core workflow solid; several features wired but not exposed in UI |
| Code quality | 5/10 | Clean in places; critical bugs in face-api.js conflict, export flow, API key storage |
| UX | 6/10 | Dark, consistent, keyboard-driven; needs virtual scrolling and component breakdown |
| Test coverage | 0/10 | Zero tests anywhere in the codebase |

---

## 10. REBUILD RECOMMENDATIONS (Phase 2 Preview)

### Frontend
- Migrate to **React 18 + TypeScript** with Vite
- Use **TanStack Virtual** for the image grid
- **Zustand** or **Jotai** for global state
- Store images as `{ id, filePath, thumbnail (256px base64), metadata }` — NOT full base64
- Single IPC call path: renderer → IPC → main → sidecar (no direct `fetch()` from renderer)

### Backend
- Split `draco_server.py` into modules: `routes/`, `models/`, `services/`
- Add explicit **VRAM budget manager** that unloads models when not in use
- Replace `trueskill` with `openskill`
- Replace `deepface` TF dependency with `onnx` emotion classifier
- Add `/models/download` and `/models/ensure` endpoints that `model-manager.js` depends on
- Pin SSCD via `torch.hub` to a specific commit hash

### Infrastructure
- Add **SQLite WAL mode** and batch writes (deferred `_save()`)
- Add **test harness**: `vitest` for JS, `pytest` for Python
- Track image file paths through entire pipeline; build base64-only for inference calls

---

*End of audit — 2026-04-04*
