# Draco Dataset Studio — Model & Provider Matrix

**Version**: 6.0.0 (Production Rebuild)
**Authored**: 2026-04-04
**Purpose**: Authoritative reference for every model, library, and external service considered during the rebuild. Determines what is integrated, how, and why.

---

## How to Read This Table

| Column | Meaning |
|--------|---------|
| **Name** | Library/model/service name |
| **Category** | Functional domain |
| **Status** | `maintained` / `stale` / `archived` / `deprecated` / `unknown` |
| **Integration Mode** | See modes below |
| **Notes** | Key facts, risks, why kept or replaced |
| **Replacement** | What replaces it (if applicable) |

**Integration Modes:**
- `core` — Ships in the default install. Always available.
- `optional-provider` — Plugin-style; loaded on demand if configured. GPU/download optional.
- `optional-service` — Requires an external service or API key.
- `inspiration-only` — Algorithm or UX concept ported; library not used.
- `avoid` — Explicitly excluded. Do not reintroduce.

---

## 1. CAPTIONING MODELS

| Name | Category | Status | Integration Mode | Notes | Replacement |
|------|----------|--------|-----------------|-------|-------------|
| **Florence-2 base/large** | Captioning | Maintained (Microsoft) | `optional-provider` | Strong open-source VLM. v5 uses `trust_remote_code=True` — acceptable for local-only app when user explicitly opts in. Use float16, batch inference. Primary local option. | — |
| **JoyCaption Alpha 2** | Captioning | Maintained (fpgaminer) | `optional-provider` | Purpose-built for anime/illustration training data. Best for stylized content. HuggingFace model, ~7B. Requires ~4GB VRAM for float16. | — |
| **Qwen2.5-VL 7B/72B** | Captioning + Reasoning | Maintained (Alibaba) | `optional-provider` | Excellent structured output support. 7B fits on 6GB VRAM at 4-bit. Strong multilingual. Use via `transformers` or Ollama. | — |
| **LLaVA-NeXT (1.6)** | Captioning | Maintained | `optional-provider` | Good quality, widely available via Ollama (`llava:13b`). No `trust_remote_code`. Good fallback when Florence-2 is too heavy. | — |
| **Moondream 2** | Captioning | Maintained | `optional-provider` | 1.86B params — runs on CPU. Excellent for lightweight/offline use. Low quality vs. larger models but negligible VRAM. | — |
| **BLIP-2** | Captioning | Stale (Salesforce, 2023) | `avoid` | Superseded by Florence-2 and LLaVA-NeXT in quality. Still available in `transformers` but not worth maintaining a provider for when better options exist. | Florence-2 |
| **CogVLM / CogVLM2** | Captioning | Maintained (Tsinghua) | `optional-provider` | No `trust_remote_code`. Good structured captioning. 7B and 17B variants. Worth a provider implementation for users who want an alternative to Florence-2. | — |
| **InternVL2** | Captioning + Reasoning | Maintained | `optional-provider` | State-of-art open VLM as of 2025. 4B and 8B variants practical. Available via Ollama. Add as `optional-provider` in Phase 3C+. | — |
| **Ollama (local VLMs)** | Captioning (proxy) | Maintained | `core` | Runs any local GGUF model with vision. Acts as a provider proxy — the `OllamaCaptionProvider` talks to localhost:11434 and supports any model the user has pulled. Critical for offline use. | — |
| **LM Studio** | Captioning (proxy) | Maintained | `optional-provider` | OpenAI-compatible local API. Same provider code as Ollama with different base URL. | — |

---

## 2. REMOTE / API CAPTIONING

| Name | Category | Status | Integration Mode | Notes | Replacement |
|------|----------|--------|-----------------|-------|-------------|
| **Gemini 2.0 Flash / Pro** | Caption + Reasoning | Maintained (Google) | `optional-service` | Best cost/quality ratio for API vision. 1M context. Multimodal native. Primary recommended API option. | — |
| **GPT-4o / GPT-4o mini** | Caption + Reasoning | Maintained (OpenAI) | `optional-service` | High quality, high cost. GPT-4o mini is practical for bulk. Supports structured output (JSON mode). | — |
| **Claude 3.5 Sonnet / Haiku** | Caption + Reasoning | Maintained (Anthropic) | `optional-service` | Best structured reasoning. Haiku is cost-effective for bulk. Use for Dataset Coach recommendations. | — |
| **Groq (LLaMA 3.2 Vision)** | Captioning | Maintained | `optional-service` | Fastest API inference. LLaMA 3.2 11B Vision available. Good for rapid iteration. | — |
| **OpenRouter** | Caption (proxy) | Maintained | `optional-service` | Multi-provider proxy. Implement as a provider that delegates to OpenRouter's OpenAI-compatible API. Adds provider coverage without per-provider code. | — |
| **Replicate** | Caption + Editing | Maintained | `optional-service` | API access to many models (Florence-2, SDXL, etc.). Useful for outpainting when local diffusion is unavailable. | — |
| **fal.ai** | Caption + Editing | Maintained | `optional-service` | Fast serverless inference. Primary recommended API for outpainting (Flux Inpainting). | — |

---

## 3. FACE DETECTION & ANALYSIS

| Name | Category | Status | Integration Mode | Notes | Replacement |
|------|----------|--------|-----------------|-------|-------------|
| **InsightFace (buffalo_l)** | Face detection + embedding + attributes | Stale on PyPI (0.7.3, 2023) — maintained on GitHub | `core` | ArcFace 512-d is the gold standard for face similarity in this domain. Yaw/pitch/roll head pose from 5-point landmarks is accurate and fast. ONNX runtime — no TF dependency. **Keep as the primary face pipeline.** Pin to GitHub main. | — |
| **@vladmandic/face-api** | Face detection (browser) | Maintained (vladmandic fork) | `avoid` | v5 loads TWO versions simultaneously causing namespace collision. In v6, ALL face analysis moves to the Python sidecar. No browser-side face detection needed. | InsightFace via sidecar |
| **face-api.js (0.22.2)** | Face detection (browser) | Archived (2020) | `avoid` | Dead. Bundled in v5's vendor folder. Remove entirely. | InsightFace via sidecar |
| **BlazeFace (TF.js)** | Face detection (browser) | Stale (abandoned 2021) | `avoid` | Used for real-time preview in v5. In v6, import thumbnail is generated server-side and there is no need for browser-side detection. Remove. | InsightFace via sidecar |
| **DeepFace** | Face attributes (emotion/age/gender) | Maintained | `avoid` | TensorFlow dependency adds 1.5GB to install and conflicts with PyTorch. Emotion/age/gender available through InsightFace attribute model (ONNX). Eliminate DeepFace. | InsightFace attrs + ONNX emotion classifier |
| **CompreFace** | Face recognition (service) | Maintained | `optional-service` | Open-source face recognition REST service. Useful for multi-machine or server deployments. Not needed for local mode. | — |
| **MediaPipe Face Landmarker** | Face detection + 478 landmarks | Maintained (Google) | `optional-provider` | 478-point mesh for detailed expression analysis. Runs in Python (mediapipe package). Good complement to InsightFace 5-point when AU/gaze needed. | — |

---

## 4. POSE ESTIMATION

| Name | Category | Status | Integration Mode | Notes | Replacement |
|------|----------|--------|-----------------|-------|-------------|
| **MediaPipe Pose** | Body pose | Maintained (Google) | `optional-provider` | Reliable 33-keypoint body pose. Python package available. No GPU required. Fast on CPU. Primary PoseProvider implementation. | — |
| **MMPose** | Body + hand pose | Maintained (OpenMMLab) | `optional-provider` | Comprehensive pose library. Heavier install. Use for high-accuracy body keypoints when MediaPipe is insufficient. | — |
| **OpenPose** | Body pose | Stale (2019 peak) | `inspiration-only` | Original academic landmark but installation is painful and CUDA-version-locked. Not used directly — algorithm concepts live on in MMPose. | MediaPipe Pose |
| **RTMPose** | Body pose (ONNX) | Maintained | `optional-provider` | ONNX export of MMPose top-down model. Fast, no PyTorch required. Add as lightweight PoseProvider. | — |

---

## 5. GAZE & ACTION UNITS

| Name | Category | Status | Integration Mode | Notes | Replacement |
|------|----------|--------|-----------------|-------|-------------|
| **L2CS-Net** | Gaze estimation | Maintained | `optional-provider` | ONNX-exportable gaze model. Predicts pitch/yaw from face crop. No TF. ~200MB. | — |
| **py-feat** | Action Units (AU) | Maintained | `optional-provider` | Python Facial Action Coding System library. Wraps multiple AU detectors. Can use ONNX backend. Use for smile/blink/expression intensity analysis. | — |
| **OpenFace** | Action Units | Stale (2018) | `inspiration-only` | Gold standard AU detector but C++ only with painful build process. Not integrated directly — py-feat's OpenFace-compatible mode is used instead. | py-feat |

---

## 6. SCENE UNDERSTANDING

| Name | Category | Status | Integration Mode | Notes | Replacement |
|------|----------|--------|-----------------|-------|-------------|
| **Color Variance Background Classifier** | Scene | — (in-house, v5) | `core` | Deterministic, fast, no GPU. Classifies background neutrality by sampling border pixels. Keep as the fast default SceneUnderstandingProvider. | — |
| **CLIP Zero-Shot Classification** | Scene tagging | Maintained | `optional-provider` | Use CLIP text embeddings to classify scene tags ("indoor", "outdoor", "studio") via cosine similarity to text prompts. No training needed. Reuses the embedding provider. | — |
| **Places365** | Scene classification | Maintained (pretrained) | `optional-provider` | ResNet-50 trained on 365 scene categories. ONNX export available. Lightweight and accurate for indoor/outdoor/environment type. | — |

---

## 7. QUALITY SCORING

| Name | Category | Status | Integration Mode | Notes | Replacement |
|------|----------|--------|-----------------|-------|-------------|
| **DracoFlow v4** | Composite quality | — (in-house, v5) | `core` | 9-metric weighted composite. Algorithm is well-designed and should be preserved exactly. Weights: sharpness (20%), face quality (20%), aesthetic (15%), brightness (10%), contrast (10%), saturation (5%), face centering (10%), background (5%), pose (5%). | — |
| **DracoFlow v2 (browser-side)** | Composite quality | — (in-house, v5) | `avoid` | Parallel implementation with 6 metrics running in the browser. Eliminated in v6. Only DracoFlow v4 (server-side) remains. | DracoFlow v4 |
| **LAION Aesthetic Predictor v2** | Aesthetic scoring | Maintained | `core` | CLIP-based aesthetic classifier trained on LAION-Aesthetics. ONNX export available. ~150MB. Primary aesthetic metric for DracoFlow v4. | — |
| **IQA-PyTorch (pyiqa)** | Image quality (NR-IQA) | Maintained | `optional-provider` | 40+ no-reference quality metrics (MUSIQ, NIQE, BRISQUE, CLIP-IQA+). Use for detailed quality breakdown in the Coach view. | — |
| **CLIP-IQA+** | Aesthetic + quality | Maintained | `optional-provider` | CLIP-based IQA that correlates well with human perception. Available in pyiqa. Useful for the quality metric breakdown panel. | — |
| **SSCD (Self-Supervised Copy Detection)** | Semantic similarity | Maintained (Meta) | `optional-provider` | Better than pHash for near-duplicate detection. v5 loads via `torch.hub` (requires internet). In v6, cache the ONNX export locally. | — |

---

## 8. EMBEDDINGS

| Name | Category | Status | Integration Mode | Notes | Replacement |
|------|----------|--------|-----------------|-------|-------------|
| **FastEmbed (ONNX CLIP)** | Image + text embedding | Maintained (Qdrant team) | `core` | ONNX runtime, no PyTorch required. Runs on CPU. `clip-ViT-B-32-visual` gives 512-d vectors. Primary EmbeddingProvider. Fast batch inference. | — |
| **OpenCLIP / PyTorch CLIP** | Image + text embedding | Maintained | `optional-provider` | Larger models (ViT-L/14 = 768-d). Use when higher embedding quality is needed for semantic search / duplicate detection. | — |
| **SentenceTransformers** | Text embedding | Maintained (SBERT) | `optional-provider` | For pure text embedding (caption similarity, search). Use `all-MiniLM-L6-v2` (22MB, fast). | — |

---

## 9. VECTOR DATABASES

| Name | Category | Status | Integration Mode | Notes | Replacement |
|------|----------|--------|-----------------|-------|-------------|
| **Qdrant (embedded)** | Vector store | Maintained | `core` | Python package `qdrant-client` supports in-process embedded mode (no separate server). Persistent on disk. Supports cosine, dot, euclidean. Collections: `image_embeddings`, `face_embeddings`. Primary vector store. | — |
| **ChromaDB** | Vector store | Maintained | `avoid` | Good library but adds a separate dependency when Qdrant embedded covers the use case. Not needed alongside Qdrant. | Qdrant |
| **FAISS** | Vector store | Maintained (Meta) | `avoid` | Fast for pure ANN search but no metadata filtering, no persistence story without extra code. Qdrant handles both. | Qdrant |
| **localStorage (btoa embeddings)** | Vector store (v5) | — | `avoid` | v5 stores CLIP embeddings as base64 JSON in localStorage. 5-10MB limit, no indexing. Completely eliminated. | Qdrant |

---

## 10. RANKING

| Name | Category | Status | Integration Mode | Notes | Replacement |
|------|----------|--------|-----------------|-------|-------------|
| **openskill** | Bayesian ranking | Maintained | `core` | Actively maintained successor to TrueSkill. PlackettLuce model. Python 3.11+ tested. API is `rate([[winner], [loser]])`. Drop-in replacement for trueskill semantics. | — |
| **trueskill** | Bayesian ranking | Unmaintained (2019) | `avoid` | Last updated 2019. Python 3.11+ not tested. Multiple open issues. Replace with openskill. | openskill |
| **Elo (custom)** | Simple ranking | `inspiration-only` | `inspiration-only` | Simpler than TrueSkill but ignores uncertainty. Use openskill instead; it handles Elo-equivalent updates as a degenerate case. | openskill |

---

## 11. IMAGE EDITING & AUGMENTATION

| Name | Category | Status | Integration Mode | Notes | Replacement |
|------|----------|--------|-----------------|-------|-------------|
| **Pillow (PIL)** | Basic editing | Maintained | `core` | Flip, crop, rotate, brightness/contrast/color jitter, format conversion. CPU only. No GPU required. PillowImageEditor is the default ImageEditor. | — |
| **OpenCV** | Image processing | Maintained | `core` | Already a dependency via InsightFace. Use for pHash, Laplacian sharpness, color analysis. Not exposed as a standalone provider — utility library only. | — |
| **rembg (BRIA RMBG-2.0)** | Background removal | Maintained | `optional-provider` | Accurate background removal via U2Net/BRIA. Already in v5 sidecar. Keep as `/remove-background` endpoint. | — |
| **Stable Diffusion (SD 1.5)** | Generative editing | Maintained | `optional-provider` | Via ComfyUI or A1111 API. SD 1.5 is compact (~2GB) and widely available. Use for outpainting on lower-VRAM systems. | — |
| **SDXL (Stable Diffusion XL)** | Generative editing | Maintained | `optional-provider` | Higher quality than SD 1.5. ~6.5GB model. Practical on 8GB+ VRAM. Good for outpainting and inpainting. | — |
| **Flux (Flux.1 Dev/Schnell)** | Generative editing | Maintained (Black Forest Labs) | `optional-provider` | State-of-art image generation/editing as of 2025. Flux.1 Schnell is fast and permissive. Primary recommended local diffusion backend for outpainting. | — |
| **ControlNet** | Conditional generation | Maintained | `optional-provider` | Pose/depth-conditioned generation. Useful for AngleGenerator (generate from different angle given pose). Use via ComfyUI backend. | — |
| **IP-Adapter** | Identity-consistent generation | Maintained | `optional-provider` | Preserve subject identity in generated variations. Key for AngleGenerator and expression editing. Use via ComfyUI backend. | — |
| **ComfyUI** | Diffusion workflow engine | Maintained | `optional-service` | Acts as a local inference backend. `ComfyUIOutpaintProvider` POSTs workflows to localhost:8188. User manages ComfyUI install separately. | — |
| **AUTOMATIC1111 (A1111)** | Diffusion inference UI | Maintained | `optional-service` | Alternative local diffusion backend. OpenAI-compatible API (`/sdapi/v1/img2img`). Less flexible than ComfyUI for complex workflows. | — |
| **fal.ai (Flux Inpainting)** | Outpainting (API) | Maintained | `optional-service` | Primary recommended API for outpainting when no local diffusion is available. Fast, pay-per-use. `FalAIOutpaintProvider`. | — |
| **Wavespeed API** | Outpainting (API) | Maintained | `optional-service` | Secondary API outpainting option. Referenced in v5 cost tables. `WavespeedOutpaintProvider`. | — |

---

## 12. CLUSTERING & ML UTILITIES

| Name | Category | Status | Integration Mode | Notes | Replacement |
|------|----------|--------|-----------------|-------|-------------|
| **HDBSCAN** | Clustering | Maintained | `core` | Density-based clustering for face embeddings. No need to specify K. Handles noise. Already in v5 requirements. | — |
| **scikit-learn** | ML utilities | Maintained | `core` | AgglomerativeClustering (alternative to HDBSCAN), cosine similarity. Already in v5. | — |
| **UMAP** | Dimensionality reduction | Maintained | `optional-provider` | 2D/3D projection of embedding space for visualization. Add to Coach view analytics. Already in v5 requirements. | — |

---

## 13. STORAGE, EXPORT & FORMATS

| Name | Category | Status | Integration Mode | Notes | Replacement |
|------|----------|--------|-----------------|-------|-------------|
| **Local filesystem** | Primary storage | — | `core` | `LocalStorageProvider` backed by `pathlib.Path`. Images stored at `~/.draco/projects/{id}/assets/`. | — |
| **better-sqlite3** | SQLite (Node.js) | Maintained | `core` | Used by Electron main process for minimal IPC (window state, Python process lifecycle). NOT the primary DB — that's SQLAlchemy + aiosqlite in the Python backend. | sql.js |
| **sql.js** | SQLite (WASM) | Maintained | `avoid` | Used in v5. Designed for browsers, not Node.js. Writes entire DB to disk on every mutation. Replace with `better-sqlite3` for Electron-side usage. | better-sqlite3 |
| **aiosqlite** | SQLite async driver | Maintained | `core` | Async SQLite driver used by SQLAlchemy 2.0 in the Python backend. | — |
| **Alembic** | DB migrations | Maintained | `core` | Schema migrations for the Python backend SQLite DB. Required — v5 had no migration story. | — |
| **JSZip** | ZIP export (browser) | Maintained | `core` | Used in v5 for caption ZIP downloads. Keep for small exports triggered from the browser. | — |
| **HuggingFace Datasets** | Export format | Maintained | `optional-provider` | `HuggingFaceDatasetExportProvider` generates `dataset_infos.json` + Parquet shards. Required for Kohya/EveryDream/SimpleTuner training pipelines. | — |

---

## 14. FRONTEND LIBRARIES

| Name | Category | Status | Integration Mode | Notes | Replacement |
|------|----------|--------|-----------------|-------|-------------|
| **React 18** | UI framework | Maintained | `core` | Component system solves the monolith problem. Concurrent mode for non-blocking rendering. | Vanilla JS monolith |
| **TypeScript 5** | Type safety | Maintained | `core` | Catches provider interface mismatches at compile time. Required. | — |
| **Vite 6** | Build tool | Maintained | `core` | Fast HMR, native ESM, Electron-compatible. | — |
| **Zustand 5** | State management | Maintained | `core` | Minimal boilerplate. Slice pattern for separated concerns. No Redux overhead. | Global mutable arrays |
| **TanStack Query 5** | Server state | Maintained | `core` | Handles loading/error/stale for API data. Background refetching. | Manual fetch + state |
| **TanStack Virtual 3** | Grid virtualization | Maintained | `core` | Virtualizes the image grid — constant DOM node count regardless of dataset size. Critical performance fix. | — |
| **React Router 7** | Client routing | Maintained | `core` | View-level navigation (not URL-based, but history-based for back/forward). | — |
| **Radix UI** | Accessible primitives | Maintained | `core` | Unstyled accessible components (Dialog, Tooltip, Dropdown, etc.). Style with CSS variables. | — |

---

## 15. PYTHON INFRASTRUCTURE

| Name | Category | Status | Integration Mode | Notes | Replacement |
|------|----------|--------|-----------------|-------|-------------|
| **FastAPI 0.115+** | Web framework | Maintained | `core` | Already in use. Async throughout. OpenAPI docs auto-generated (useful for frontend type generation). | — |
| **uvicorn** | ASGI server | Maintained | `core` | FastAPI's standard runner. | — |
| **SQLAlchemy 2.0** | ORM | Maintained | `core` | Async ORM with mapped_column style. Replaces the sql.js DB entirely. | sql.js |
| **Pydantic v2** | Validation | Maintained | `core` | FastAPI uses Pydantic v2 for request/response models. Use for all dataclasses that cross the API boundary. | — |
| **cryptography (Fernet)** | Secrets | Maintained | `core` | AES-256 API key encryption. Replaces the XOR-hardcoded-key "encryption" in v5. | XOR obfuscation |
| **numpy 2.x** | Numerics | Maintained | `core` | Pin carefully — 2.x has breaking changes vs 1.x. Test with InsightFace and ONNX runtime. | — |
| **torch 2.6+** | Deep learning | Maintained | `optional-provider` | Required by Florence-2, CLIP PyTorch, pyiqa. Mark as optional install (not required for CPU-only mode with FastEmbed). | — |
| **onnxruntime-gpu** | ONNX inference | Maintained | `core` | Required by InsightFace, FastEmbed, aesthetic model. GPU acceleration. | — |
| **transformers 4.50+** | HuggingFace models | Maintained | `optional-provider` | Required by Florence-2, LLaVA, etc. Large dependency (~500MB). | — |
| **httpx** | Async HTTP client | Maintained | `core` | Used by API providers (Gemini, OpenAI, etc.) and Ollama client. Replace `requests` for async compatibility. | requests |

---

## Summary: v5 → v6 Migration Table

| v5 Component | v6 Replacement | Reason |
|-------------|----------------|--------|
| Vanilla JS monolith (5028 lines) | React 18 + TypeScript + Vite | Scalability, maintainability |
| Global base64 image arrays | Filesystem paths + blob URLs | Memory cliff fix |
| sql.js (WASM SQLite) | SQLAlchemy 2.0 async + aiosqlite | Performance, migrations |
| trueskill | openskill | Unmaintained dependency |
| deepface (TensorFlow) | InsightFace attrs + ONNX emotion | TF/PyTorch conflict, install size |
| face-api.js 0.22.2 (bundled) | Removed | Obsolete, browser-side |
| @vladmandic/face-api (CDN) | Removed | All face work moves to Python sidecar |
| BlazeFace TF.js | Removed | Browser detection not needed in v6 |
| localStorage API keys | SQLAlchemy ProviderConfig + Fernet | Security |
| localStorage embeddings | Qdrant embedded | Scale, queryability |
| Hardcoded port 18082 (no migration) | Alembic + config | Operational maturity |
| Two conflicting pHash implementations | Single PHashDuplicateProvider | Correctness |
| DracoFlow v2 (browser) | Removed — DracoFlow v4 (server only) | Eliminates algorithm divergence |
| `trust_remote_code=True` Florence-2 | Explicit user opt-in dialog | Security UX |
| while(True) poll loop in queue.js | asyncio.Queue event-driven wake | CPU efficiency |
| torch.hub SSCD (internet required) | Cached ONNX export | Offline support |
