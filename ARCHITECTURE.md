# Draco Dataset Studio — Production Architecture

**Version**: 6.0.0 (Production Rebuild)
**Authored**: 2026-04-04
**Status**: Authoritative design document — implement against this spec

---

## 1. RUNTIME STACK

### Overview

```
┌─────────────────────────────────────────────────────────────────┐
│                        Electron Shell                           │
│  (window management, file dialogs, tray, auto-updater)         │
│                                                                 │
│  ┌───────────────────────────────────────────────────────────┐ │
│  │              React Frontend (Vite + TypeScript)           │ │
│  │  Zustand state │ React Query cache │ Virtualized grid     │ │
│  │  Blob URL pool │ Object URL cache  │ Dark theme CSS vars  │ │
│  └────────────────────────┬──────────────────────────────────┘ │
│                           │ REST HTTP (localhost:18082)         │
│  ┌────────────────────────▼──────────────────────────────────┐ │
│  │              FastAPI Backend (Python 3.11+)               │ │
│  │  Async routers │ Provider registry │ Task scheduler       │ │
│  │  SQLAlchemy 2.0 async ORM (SQLite WAL)                   │ │
│  │  Qdrant embedded │ StorageProvider (local FS)            │ │
│  └───────────────────────────────────────────────────────────┘ │
└─────────────────────────────────────────────────────────────────┘
```

### Technology Decisions

| Layer | Technology | Justification |
|-------|-----------|---------------|
| Desktop shell | Electron 35.x | Already in use; large community; good native file/dialog support |
| Frontend framework | React 18 + TypeScript 5 | Component system solves the monolith problem; TS catches interface mismatches at compile time |
| Frontend build | Vite 6 | Fast HMR; native ESM; works well with Electron's renderer process |
| State management | Zustand 5 | Lightweight; no boilerplate; supports slices cleanly |
| Server-state cache | TanStack Query 5 | Handles loading/error/stale states; reduces duplicate fetches |
| Backend framework | FastAPI 0.115+ | Already in use and well-suited; async-first; OpenAPI docs auto-generated |
| Background tasks | asyncio + ThreadPoolExecutor | Sufficient for local mode; avoids Redis dependency; GPU tasks are naturally serialized by VRAM budget |
| ORM | SQLAlchemy 2.0 async | Type-safe; async-native in 2.0; migration support via Alembic |
| Database | SQLite (WAL mode) | Local-first; zero infra; WAL enables concurrent reads during writes |
| Vector store | Qdrant embedded (Python lib) | No separate process; in-process; supports cosine/dot similarity; persistent on disk |
| Image storage | Local filesystem + blob URLs | Eliminates base64-in-memory cliff; thumbnails cached to disk |
| IPC pattern | REST over localhost | Cleaner than Electron IPC for AI tasks; independently testable; portable to web/Tauri later |

### Why NOT Next.js
This is a local desktop app. Next.js requires a Node server and SSR concepts that add complexity with no benefit. Vite produces a static bundle that Electron loads directly from disk — no server required.

### Why NOT Celery/Redis
Redis adds a separate process and installation requirement. For a local desktop app running on one machine, `asyncio.Queue` + `ThreadPoolExecutor` for CPU-bound tasks is sufficient. The GPU serialization is already enforced by the VRAM budget manager (one GPU task at a time). Celery can be added later if a hosted/multi-user mode is needed.

---

## 2. PROVIDER ARCHITECTURE

### Design Principles

1. **Every capability is behind an abstract interface.** No concrete model call appears in business logic — only provider method calls.
2. **Providers are registered at startup** via a `ProviderRegistry` dependency-injected into all routers.
3. **Fallback chains are declared in config**, not hardcoded in routes.
4. **Provider availability is actively checked**, not assumed.
5. **All providers are async**. Blocking GPU work runs in `loop.run_in_executor(thread_pool, ...)`.

### Base Provider Pattern

```python
# backend/providers/base.py

from abc import ABC, abstractmethod
from typing import Any

class BaseProvider(ABC):
    """All providers inherit from this."""

    provider_id: str       # e.g. "insightface_local"
    display_name: str      # e.g. "InsightFace (Local)"
    requires_gpu: bool = False
    vram_mb: int = 0       # Estimated peak VRAM usage in MB

    @abstractmethod
    async def is_available(self) -> bool:
        """Return True if this provider can accept requests right now."""
        ...

    @abstractmethod
    async def health_check(self) -> dict[str, Any]:
        """Return status dict with 'ok', 'latency_ms', and optional 'details'."""
        ...

    async def load(self) -> None:
        """Optional: pre-warm the model. Called by VRAM budget manager."""
        pass

    async def unload(self) -> None:
        """Optional: release GPU memory. Called by VRAM budget manager."""
        pass
```

---

### 2.1 CaptionProvider

```python
# backend/providers/caption/base.py

from dataclasses import dataclass
from enum import Enum
from .base import BaseProvider

class CaptionMode(str, Enum):
    MINIMAL = "minimal"        # Short, tag-like
    DETAILED = "detailed"      # Full natural language
    STRUCTURED = "structured"  # JSON with fields: subject, action, style, etc.

@dataclass
class CaptionRequest:
    image_path: str            # Absolute path to image on disk
    mode: CaptionMode = CaptionMode.DETAILED
    system_prompt: str | None = None
    trigger_word: str | None = None
    max_tokens: int = 512
    temperature: float = 0.7

@dataclass
class CaptionResult:
    text: str
    provider_id: str
    model_name: str
    tokens_used: int | None = None
    latency_ms: float = 0.0
    cost_usd: float = 0.0
    raw_response: dict | None = None  # Full provider response for debugging

class CaptionProvider(BaseProvider):
    @abstractmethod
    async def caption(self, request: CaptionRequest) -> CaptionResult: ...

    async def caption_batch(
        self,
        requests: list[CaptionRequest],
        concurrency: int = 4,
    ) -> list[CaptionResult]:
        """Default: sequential. Override for true batching."""
        import asyncio
        sem = asyncio.Semaphore(concurrency)
        async def _one(r):
            async with sem:
                return await self.caption(r)
        return await asyncio.gather(*[_one(r) for r in requests])
```

**Implementations to build:**
- `Florence2CaptionProvider` — local HuggingFace, float16, batched
- `OllamaCaptionProvider` — HTTP to localhost:11434
- `GeminiCaptionProvider` — Google AI API
- `OpenAICaptionProvider` — GPT-4o Vision API
- `AnthropicCaptionProvider` — Claude Vision API

---

### 2.2 VisionReasoningProvider

```python
@dataclass
class VisionReasoningRequest:
    image_path: str
    question: str              # "Does this image show good lighting?"
    system_prompt: str | None = None
    structured_output_schema: dict | None = None  # JSON Schema for structured responses

@dataclass
class VisionReasoningResult:
    answer: str
    structured: dict | None = None  # Parsed if structured_output_schema was provided
    confidence: float | None = None
    provider_id: str = ""
    latency_ms: float = 0.0

class VisionReasoningProvider(BaseProvider):
    @abstractmethod
    async def reason(self, request: VisionReasoningRequest) -> VisionReasoningResult: ...
```

**Implementations:** Same set as CaptionProvider (VLMs handle both). Add `Qwen25VLProvider`.

---

### 2.3 EmbeddingProvider

```python
@dataclass
class EmbeddingRequest:
    image_path: str | None = None   # Provide one of these
    text: str | None = None
    model_name: str = "default"

@dataclass
class EmbeddingResult:
    vector: list[float]        # Normalized embedding vector
    dimension: int
    provider_id: str
    model_name: str

class EmbeddingProvider(BaseProvider):
    @property
    @abstractmethod
    def dimension(self) -> int: ...  # e.g. 512, 768, 1024

    @abstractmethod
    async def embed_image(self, image_path: str) -> EmbeddingResult: ...

    @abstractmethod
    async def embed_text(self, text: str) -> EmbeddingResult: ...

    async def embed_image_batch(
        self, image_paths: list[str], batch_size: int = 32
    ) -> list[EmbeddingResult]: ...
```

**Implementations:** `FastEmbedProvider` (ONNX CLIP, CPU-compatible), `CLIPProvider` (PyTorch).

---

### 2.4 FaceDetectionProvider

```python
@dataclass
class BoundingBox:
    x: float; y: float; w: float; h: float  # Normalized 0-1

@dataclass
class FaceLandmarks:
    points: list[tuple[float, float]]  # Normalized (x, y) pairs
    format: str = "5pt"                # "5pt" | "68pt" | "478pt"

@dataclass
class DetectedFace:
    bbox: BoundingBox
    confidence: float
    landmarks: FaceLandmarks | None = None
    face_index: int = 0

@dataclass
class FaceDetectionResult:
    faces: list[DetectedFace]
    image_width: int
    image_height: int
    provider_id: str
    latency_ms: float = 0.0

class FaceDetectionProvider(BaseProvider):
    @abstractmethod
    async def detect(self, image_path: str) -> FaceDetectionResult: ...

    async def detect_batch(
        self, image_paths: list[str], batch_size: int = 8
    ) -> list[FaceDetectionResult]: ...
```

**Implementations:** `InsightFaceDetectionProvider`, `MediaPipeFaceDetectionProvider`.

---

### 2.5 FaceEmbeddingProvider

```python
@dataclass
class FaceEmbeddingRequest:
    image_path: str
    face: DetectedFace      # Pre-detected face bounding box

@dataclass
class FaceEmbeddingResult:
    embedding: list[float]  # ArcFace 512-d or similar
    dimension: int
    provider_id: str

class FaceEmbeddingProvider(BaseProvider):
    @property
    @abstractmethod
    def dimension(self) -> int: ...

    @abstractmethod
    async def embed_face(self, request: FaceEmbeddingRequest) -> FaceEmbeddingResult: ...

    async def embed_faces_batch(
        self, requests: list[FaceEmbeddingRequest]
    ) -> list[FaceEmbeddingResult]: ...
```

**Implementations:** `InsightFaceArcFaceProvider` (512-d, the gold standard — preserve from v5).

---

### 2.6 FaceRecognitionProvider

```python
@dataclass
class FaceMatch:
    identity_id: str
    similarity: float        # 0.0-1.0 cosine similarity
    confidence: float

@dataclass
class FaceRecognitionResult:
    matches: list[FaceMatch]
    is_new_identity: bool
    suggested_identity_id: str | None = None

class FaceRecognitionProvider(BaseProvider):
    @abstractmethod
    async def recognize(
        self,
        embedding: list[float],
        threshold: float = 0.45,
    ) -> FaceRecognitionResult: ...
```

**Implementation:** `QdrantFaceRecognitionProvider` — queries face embeddings in Qdrant.

---

### 2.7 FaceAttributeProvider

```python
@dataclass
class FaceAttributes:
    age: float | None = None
    gender: str | None = None          # "male" | "female" | "unknown"
    gender_confidence: float | None = None
    emotion: str | None = None         # "happy" | "sad" | "neutral" | ...
    emotion_scores: dict[str, float] | None = None  # All emotion probabilities
    race: str | None = None
    race_confidence: float | None = None

class FaceAttributeProvider(BaseProvider):
    @abstractmethod
    async def analyze(
        self,
        image_path: str,
        face: DetectedFace,
    ) -> FaceAttributes: ...
```

**Implementations:** `InsightFaceAttributeProvider`, `ONNXEmotionProvider` (replaces DeepFace).

---

### 2.8 HeadPoseProvider

```python
@dataclass
class HeadPose:
    yaw: float    # -90 to 90, left/right rotation
    pitch: float  # -90 to 90, up/down tilt
    roll: float   # -90 to 90, head tilt
    is_frontal: bool   # abs(yaw) < 15 and abs(pitch) < 15

class HeadPoseProvider(BaseProvider):
    @abstractmethod
    async def estimate(
        self,
        image_path: str,
        face: DetectedFace,
        landmarks: FaceLandmarks,
    ) -> HeadPose: ...
```

**Implementation:** `InsightFaceHeadPoseProvider` (already in v5 sidecar — preserve).

---

### 2.9 GazeProvider

```python
@dataclass
class GazeEstimate:
    pitch: float    # Vertical gaze angle (radians)
    yaw: float      # Horizontal gaze angle (radians)
    is_looking_at_camera: bool
    confidence: float

class GazeProvider(BaseProvider):
    @abstractmethod
    async def estimate(
        self,
        image_path: str,
        face: DetectedFace,
    ) -> GazeEstimate: ...
```

**Implementation:** `L2CSNetGazeProvider` (ONNX, no TF dependency).

---

### 2.10 ActionUnitProvider

```python
@dataclass
class ActionUnitResult:
    aus: dict[str, float]   # e.g. {"AU1": 0.8, "AU6": 0.2, ...}
    smile_intensity: float  # Derived from AU6 + AU12
    blink_detected: bool    # AU46

class ActionUnitProvider(BaseProvider):
    @abstractmethod
    async def analyze(
        self,
        image_path: str,
        face: DetectedFace,
        landmarks: FaceLandmarks,
    ) -> ActionUnitResult: ...
```

**Implementation:** `OpenFaceCompatibleAUProvider` (py-feat ONNX backend).

---

### 2.11 PoseProvider

```python
from enum import Enum

class PoseType(str, Enum):
    BODY = "body"
    HAND = "hand"
    HOLISTIC = "holistic"

@dataclass
class Keypoint:
    x: float; y: float; z: float | None = None
    visibility: float = 1.0
    name: str = ""

@dataclass
class PoseResult:
    keypoints: list[Keypoint]
    pose_type: PoseType
    shot_type: str          # "close_up" | "half_body" | "full_body"
    provider_id: str

class PoseProvider(BaseProvider):
    @abstractmethod
    async def estimate(
        self,
        image_path: str,
        pose_type: PoseType = PoseType.BODY,
    ) -> PoseResult: ...
```

**Implementations:** `MediaPipePoseProvider`, `MMPoseLightweightProvider`.

---

### 2.12 SceneUnderstandingProvider

```python
@dataclass
class SceneAnalysis:
    scene_type: str                    # "indoor" | "outdoor" | "studio"
    background_type: str               # "neutral" | "natural" | "urban" | "busy"
    lighting_quality: str              # "well_lit" | "harsh" | "low_light"
    composition_score: float           # 0.0-1.0
    has_text: bool
    dominant_colors: list[str]         # Hex codes
    tags: list[str]                    # Free-form scene tags

class SceneUnderstandingProvider(BaseProvider):
    @abstractmethod
    async def analyze(self, image_path: str) -> SceneAnalysis: ...
```

**Implementations:** `ColorVarianceSceneProvider` (fast, deterministic — preserve from v5), `VLMSceneProvider` (routes to any VisionReasoningProvider).

---

### 2.13 DuplicateDetectionProvider

```python
@dataclass
class DuplicateResult:
    asset_id: str
    duplicate_of: str | None
    similarity: float
    method: str    # "phash" | "embedding" | "sscd"
    hamming_distance: int | None = None

class DuplicateDetectionProvider(BaseProvider):
    @abstractmethod
    async def compute_hash(self, image_path: str) -> str: ...

    @abstractmethod
    async def find_duplicates(
        self,
        asset_ids: list[str],
        threshold: float = 0.95,
    ) -> list[DuplicateResult]: ...
```

**Implementations:** `PHashDuplicateProvider` (single canonical implementation — replaces the two conflicting v5 implementations), `EmbeddingDuplicateProvider` (cosine similarity via Qdrant).

---

### 2.14 QualityScorer

```python
@dataclass
class QualityMetrics:
    # Photographic metrics (DracoFlow v4 — preserve algorithm)
    sharpness: float          # Laplacian variance, normalized 0-1
    face_quality: float       # InsightFace quality score 0-1
    aesthetic: float          # LAION aesthetic predictor 0-1
    brightness: float         # Mean luminance, normalized 0-1
    contrast: float           # RMS contrast, normalized 0-1
    saturation: float         # Mean HSV saturation, normalized 0-1
    face_centering: float     # Face bbox proximity to image center 0-1
    background_score: float   # Background neutrality 0-1
    pose_score: float         # Head pose frontal-ness 0-1

    # Composite
    dracoflow_score: float    # Weighted composite (preserve v4 weights)
    ai_score: float | None    # From VLM review pass (optional)
    final_score: float        # dracoflow_score if no AI, else 0.55*dflow + 0.45*ai

    # Flags
    is_blurry: bool
    is_overexposed: bool
    is_underexposed: bool
    has_face: bool

class QualityScorer(BaseProvider):
    @abstractmethod
    async def score(self, image_path: str) -> QualityMetrics: ...

    async def score_batch(
        self, image_paths: list[str], batch_size: int = 16
    ) -> list[QualityMetrics]: ...
```

**Implementation:** `DracoFlowV4QualityScorer` — the v4 algorithm is correct and should be the only implementation. The v2 browser-side version is eliminated.

---

### 2.15 RankingEngine

```python
@dataclass
class RankingPlayer:
    asset_id: str
    mu: float        # Mean skill estimate (openskill PlackettLuce)
    sigma: float     # Uncertainty
    rank: int        # Derived rank (1 = best)
    comparisons: int # Number of pairwise comparisons

@dataclass
class ComparisonResult:
    winner_id: str
    loser_id: str
    is_draw: bool = False
    judge: str = "human"  # "human" | provider_id for AI judge

class RankingEngine(BaseProvider):
    @abstractmethod
    async def get_next_pair(
        self,
        session_id: str,
        strategy: str = "uncertainty_first",
    ) -> tuple[str, str]: ...

    @abstractmethod
    async def record_comparison(
        self,
        session_id: str,
        result: ComparisonResult,
    ) -> None: ...

    @abstractmethod
    async def get_rankings(
        self,
        session_id: str,
    ) -> list[RankingPlayer]: ...

    @abstractmethod
    async def undo_last(self, session_id: str) -> None: ...
```

**Implementation:** `OpenSkillRankingEngine` (uses `openskill` PlackettLuce model — replaces `trueskill`).

---

### 2.16 ImageEditor

```python
@dataclass
class EditOperation:
    type: str           # "crop" | "flip" | "rotate" | "brightness" | "color_jitter"
    params: dict        # Operation-specific parameters

@dataclass
class EditResult:
    output_path: str    # Written to disk; caller decides whether to add as new asset
    operation_log: list[EditOperation]

class ImageEditor(BaseProvider):
    @abstractmethod
    async def apply(
        self,
        image_path: str,
        operations: list[EditOperation],
        output_path: str,
    ) -> EditResult: ...
```

**Implementation:** `PillowImageEditor` (CPU, no GPU required; covers all basic ops).

---

### 2.17 OutpaintingProvider

```python
@dataclass
class OutpaintRequest:
    image_path: str
    target_aspect: str        # "16:9" | "9:16" | "1:1" | "4:3" | etc.
    prompt: str = ""
    strength: float = 0.8     # Diffusion strength for outpainted region

@dataclass
class OutpaintResult:
    output_path: str
    provider_id: str
    cost_usd: float = 0.0

class OutpaintingProvider(BaseProvider):
    @abstractmethod
    async def outpaint(self, request: OutpaintRequest) -> OutpaintResult: ...
```

**Implementations:** `FalAIOutpaintProvider`, `WavespeedOutpaintProvider`, `ComfyUIOutpaintProvider`.

---

### 2.18 AngleGenerator

```python
@dataclass
class AngleGenerationRequest:
    reference_image_path: str
    target_angles: list[str]    # ["left_45", "right_45", "profile_left", "overhead"]
    prompt_context: str = ""

@dataclass
class AngleGenerationResult:
    generated_images: list[str]   # Output file paths
    target_angles: list[str]
    provider_id: str
    cost_usd: float = 0.0

class AngleGenerator(BaseProvider):
    @abstractmethod
    async def generate(self, request: AngleGenerationRequest) -> AngleGenerationResult: ...
```

**Implementations:** `IPAdapterAngleProvider`, `FalAIAngleProvider`.

---

### 2.19 DatasetBalancer

```python
@dataclass
class DatasetProfile:
    total_images: int
    pose_distribution: dict[str, int]    # {"frontal": 40, "left_45": 10, ...}
    expression_distribution: dict[str, int]
    shot_distribution: dict[str, int]    # {"close_up": 25, "half_body": 15, ...}
    quality_histogram: list[int]         # Bucketed quality scores
    gaps: list[str]                      # Human-readable gap descriptions
    health_score: float                  # 0-100

@dataclass
class BalancerRecommendation:
    gap: str
    action: str             # "generate" | "capture" | "discard"
    suggested_prompt: str   # For generative gap-filling
    priority: int           # 1 = most critical

class DatasetBalancer(BaseProvider):
    @abstractmethod
    async def analyze(self, asset_ids: list[str]) -> DatasetProfile: ...

    @abstractmethod
    async def recommend(self, profile: DatasetProfile) -> list[BalancerRecommendation]: ...
```

---

### 2.20 StorageProvider

```python
from pathlib import Path

class StorageProvider(BaseProvider):
    """Abstracts all filesystem operations. Enables future S3/GCS swap."""

    @abstractmethod
    async def write(self, key: str, data: bytes) -> str:
        """Write data under key. Returns resolved URL/path."""
        ...

    @abstractmethod
    async def read(self, key: str) -> bytes: ...

    @abstractmethod
    async def exists(self, key: str) -> bool: ...

    @abstractmethod
    async def delete(self, key: str) -> None: ...

    @abstractmethod
    async def list_keys(self, prefix: str = "") -> list[str]: ...

    @abstractmethod
    def resolve_path(self, key: str) -> Path:
        """Return the absolute filesystem path for a key."""
        ...
```

**Implementation:** `LocalStorageProvider` — stores under `~/.draco/storage/{project_id}/`.

---

### 2.21 ExportProvider

```python
@dataclass
class ExportConfig:
    format: str              # "flat" | "clustered" | "ranked" | "huggingface"
    include_captions: bool = True
    caption_format: str = "txt_sidecar"   # "txt_sidecar" | "jsonl" | "parquet"
    image_format: str = "source"          # "source" | "jpg" | "png" | "webp"
    quality: int = 95
    min_quality_score: float = 0.0        # Filter by quality
    max_images: int | None = None
    output_dir: str = ""

@dataclass
class ExportResult:
    output_path: str
    file_count: int
    total_bytes: int
    manifest_path: str | None = None

class ExportProvider(BaseProvider):
    @abstractmethod
    async def export(
        self,
        asset_ids: list[str],
        config: ExportConfig,
    ) -> ExportResult: ...
```

**Implementations:** `FlatExportProvider`, `RankedExportProvider`, `HuggingFaceDatasetExportProvider`.

---

### 2.22 TourGuideProvider

```python
@dataclass
class TourStep:
    target_selector: str    # CSS selector for the highlighted element
    title: str
    body: str
    position: str           # "top" | "bottom" | "left" | "right"
    action: str | None      # Optional action hint: "click" | "drag" | etc.

@dataclass
class Tour:
    tour_id: str
    name: str
    steps: list[TourStep]
    trigger: str            # "manual" | "first_visit" | "feature_unlock"

class TourGuideProvider(BaseProvider):
    @abstractmethod
    async def get_tour(self, tour_id: str) -> Tour: ...

    @abstractmethod
    async def list_tours(self) -> list[Tour]: ...
```

**Implementation:** `JSONFileTourGuideProvider` — tours defined in `frontend/tours/*.json`.

---

### Provider Registry

```python
# backend/providers/registry.py

from typing import Type, TypeVar

T = TypeVar("T", bound=BaseProvider)

class ProviderRegistry:
    """Singleton — one instance per application lifetime."""

    def __init__(self, config: "AppConfig"):
        self._providers: dict[str, BaseProvider] = {}
        self._chains: dict[str, list[str]] = config.provider_chains
        self._config = config

    def register(self, provider: BaseProvider) -> None:
        self._providers[provider.provider_id] = provider

    def get(self, provider_id: str) -> BaseProvider:
        if provider_id not in self._providers:
            raise KeyError(f"Provider '{provider_id}' not registered")
        return self._providers[provider_id]

    def get_typed(self, provider_id: str, expected_type: Type[T]) -> T:
        p = self.get(provider_id)
        if not isinstance(p, expected_type):
            raise TypeError(f"Provider '{provider_id}' is {type(p)}, expected {expected_type}")
        return p

    async def resolve_chain(
        self,
        chain_name: str,
        expected_type: Type[T],
    ) -> T:
        """Walk the fallback chain and return the first available provider."""
        chain = self._chains.get(chain_name, [])
        for provider_id in chain:
            try:
                p = self.get_typed(provider_id, expected_type)
                if await p.is_available():
                    return p
            except (KeyError, TypeError):
                continue
        raise RuntimeError(f"No available provider for chain '{chain_name}'")
```

### Default Provider Chains (config)

```yaml
# config/providers.yaml
provider_chains:
  caption:
    - florence2_local
    - ollama_local
    - gemini_api
    - openai_api
    - anthropic_api

  face_detection:
    - insightface_local

  face_embedding:
    - insightface_arcface

  face_attributes:
    - insightface_attrs
    - onnx_emotion

  embedding:
    - fastembed_local
    - clip_local

  quality:
    - dracoflow_v4

  ranking:
    - openskill_local

  outpainting:
    - fal_api
    - wavespeed_api
    - comfyui_local

  pose:
    - mediapipe_pose
    - mmpose_lightweight
```

---

## 3. DATA MODEL

### SQLAlchemy 2.0 Async Models

```python
# backend/models/base.py

from datetime import datetime
from sqlalchemy import func
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

class Base(DeclarativeBase):
    pass

class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(default=func.now())
    updated_at: Mapped[datetime] = mapped_column(default=func.now(), onupdate=func.now())
```

---

#### Project

```python
# backend/models/project.py

class Project(Base, TimestampMixin):
    __tablename__ = "projects"

    id: Mapped[str] = mapped_column(primary_key=True)   # UUID4
    name: Mapped[str] = mapped_column(nullable=False)
    description: Mapped[str] = mapped_column(default="")
    subject_name: Mapped[str | None]
    trigger_word: Mapped[str | None]
    training_resolution: Mapped[int] = mapped_column(default=512)
    training_preset: Mapped[str] = mapped_column(default="flux_lora")
    storage_root: Mapped[str]         # Absolute path to project storage dir
    thumbnail_path: Mapped[str | None]
    is_archived: Mapped[bool] = mapped_column(default=False)

    # Relationships
    assets: Mapped[list["Asset"]] = relationship(back_populates="project")
    ranking_sessions: Mapped[list["RankingSession"]] = relationship(back_populates="project")
    export_jobs: Mapped[list["ExportJob"]] = relationship(back_populates="project")
```

---

#### Asset

```python
class Asset(Base, TimestampMixin):
    __tablename__ = "assets"

    id: Mapped[str] = mapped_column(primary_key=True)   # UUID4
    project_id: Mapped[str] = mapped_column(ForeignKey("projects.id"), index=True)

    # Source file info
    filename: Mapped[str]
    original_path: Mapped[str]       # Absolute path to source file
    storage_key: Mapped[str]         # Key within StorageProvider
    thumbnail_key: Mapped[str | None]
    file_size_bytes: Mapped[int]
    width: Mapped[int]
    height: Mapped[int]
    format: Mapped[str]              # "jpg" | "png" | "webp" etc.
    phash: Mapped[str | None]        # 64-bit hex pHash
    sha256: Mapped[str | None]       # Content hash for dedup

    # Classification
    category: Mapped[str] = mapped_column(default="unclassified")
    # "hero" | "good" | "train" | "discard" | "duplicate" | "unclassified"
    is_selected: Mapped[bool] = mapped_column(default=False)
    is_duplicate: Mapped[bool] = mapped_column(default=False)
    duplicate_of_id: Mapped[str | None] = mapped_column(ForeignKey("assets.id"))

    # Quality scores (DracoFlow v4)
    score_sharpness: Mapped[float | None]
    score_face_quality: Mapped[float | None]
    score_aesthetic: Mapped[float | None]
    score_brightness: Mapped[float | None]
    score_contrast: Mapped[float | None]
    score_saturation: Mapped[float | None]
    score_face_centering: Mapped[float | None]
    score_background: Mapped[float | None]
    score_pose: Mapped[float | None]
    score_dracoflow: Mapped[float | None]
    score_ai: Mapped[float | None]
    score_final: Mapped[float | None]

    # Flags
    flag_blurry: Mapped[bool] = mapped_column(default=False)
    flag_overexposed: Mapped[bool] = mapped_column(default=False)
    flag_underexposed: Mapped[bool] = mapped_column(default=False)

    # Face detection
    face_count: Mapped[int] = mapped_column(default=0)
    primary_face_bbox: Mapped[str | None]    # JSON: [x,y,w,h] normalized
    face_ratio: Mapped[float | None]         # bbox_area / image_area
    shot_type: Mapped[str | None]            # "close_up" | "half_body" | "full_body"

    # Head pose (from primary face)
    pose_yaw: Mapped[float | None]
    pose_pitch: Mapped[float | None]
    pose_roll: Mapped[float | None]
    pose_is_frontal: Mapped[bool | None]

    # Emotion / attributes (from primary face)
    attr_age: Mapped[float | None]
    attr_gender: Mapped[str | None]
    attr_emotion: Mapped[str | None]
    attr_smile_intensity: Mapped[float | None]

    # Scene
    scene_type: Mapped[str | None]
    background_type: Mapped[str | None]
    lighting_quality: Mapped[str | None]

    # Identity cluster
    identity_id: Mapped[str | None] = mapped_column(ForeignKey("identity_clusters.id"))

    # Analysis state
    analysis_version: Mapped[int] = mapped_column(default=0)
    caption_count: Mapped[int] = mapped_column(default=0)
    embedding_indexed: Mapped[bool] = mapped_column(default=False)

    # Relationships
    project: Mapped["Project"] = relationship(back_populates="assets")
    captions: Mapped[list["CaptionVersion"]] = relationship(back_populates="asset")
    face_clusters: Mapped[list["FaceCluster"]] = relationship(back_populates="asset")
    identity: Mapped["IdentityCluster | None"] = relationship(back_populates="assets")
    augmentation_results: Mapped[list["AugmentationResult"]] = relationship(back_populates="source_asset")
```

---

#### CaptionVersion

```python
class CaptionVersion(Base, TimestampMixin):
    __tablename__ = "caption_versions"

    id: Mapped[str] = mapped_column(primary_key=True)
    asset_id: Mapped[str] = mapped_column(ForeignKey("assets.id"), index=True)

    text: Mapped[str]
    provider_id: Mapped[str]           # Which provider generated this
    model_name: Mapped[str]
    mode: Mapped[str]                  # "minimal" | "detailed" | "structured"
    is_active: Mapped[bool] = mapped_column(default=True)
    is_edited: Mapped[bool] = mapped_column(default=False)
    edit_diff: Mapped[str | None]      # Unified diff from original to edited
    tokens_used: Mapped[int | None]
    cost_usd: Mapped[float] = mapped_column(default=0.0)
    score_length: Mapped[float | None]
    score_density: Mapped[float | None]
    score_trigger_present: Mapped[bool | None]

    asset: Mapped["Asset"] = relationship(back_populates="captions")
```

---

#### FaceCluster

```python
class FaceCluster(Base, TimestampMixin):
    __tablename__ = "face_clusters"

    id: Mapped[str] = mapped_column(primary_key=True)
    asset_id: Mapped[str] = mapped_column(ForeignKey("assets.id"), index=True)
    face_index: Mapped[int]            # Which face in the image (0-indexed)

    bbox_json: Mapped[str]             # JSON [x,y,w,h] normalized
    landmarks_json: Mapped[str | None]
    embedding: Mapped[str | None]      # JSON float array (ArcFace 512-d)
    embedding_dim: Mapped[int] = mapped_column(default=512)
    quality_score: Mapped[float | None]

    cluster_id: Mapped[str | None]     # Assigned by HDBSCAN/agglomerative
    identity_id: Mapped[str | None] = mapped_column(ForeignKey("identity_clusters.id"))

    asset: Mapped["Asset"] = relationship(back_populates="face_clusters")
    identity: Mapped["IdentityCluster | None"] = relationship(back_populates="face_clusters")
```

---

#### IdentityCluster

```python
class IdentityCluster(Base, TimestampMixin):
    __tablename__ = "identity_clusters"

    id: Mapped[str] = mapped_column(primary_key=True)
    project_id: Mapped[str] = mapped_column(ForeignKey("projects.id"), index=True)

    label: Mapped[str]                 # User-assigned name, e.g. "Subject A"
    is_primary_subject: Mapped[bool] = mapped_column(default=False)
    representative_face_id: Mapped[str | None]  # FaceCluster id for thumbnail
    centroid_embedding: Mapped[str | None]       # JSON mean embedding vector
    member_count: Mapped[int] = mapped_column(default=0)
    thumbnail_key: Mapped[str | None]

    assets: Mapped[list["Asset"]] = relationship(back_populates="identity")
    face_clusters: Mapped[list["FaceCluster"]] = relationship(back_populates="identity")
```

---

#### RankingSession

```python
class RankingSession(Base, TimestampMixin):
    __tablename__ = "ranking_sessions"

    id: Mapped[str] = mapped_column(primary_key=True)
    project_id: Mapped[str] = mapped_column(ForeignKey("projects.id"), index=True)
    name: Mapped[str]
    algorithm: Mapped[str] = mapped_column(default="plackett_luce")
    status: Mapped[str] = mapped_column(default="active")
    # "active" | "complete" | "archived"
    total_comparisons: Mapped[int] = mapped_column(default=0)
    pairs_decided: Mapped[int] = mapped_column(default=0)
    confidence_pct: Mapped[float] = mapped_column(default=0.0)

    project: Mapped["Project"] = relationship(back_populates="ranking_sessions")
    comparisons: Mapped[list["RankingComparison"]] = relationship(back_populates="session")
```

---

#### RankingComparison

```python
class RankingComparison(Base):
    __tablename__ = "ranking_comparisons"

    id: Mapped[str] = mapped_column(primary_key=True)
    session_id: Mapped[str] = mapped_column(ForeignKey("ranking_sessions.id"), index=True)
    asset_a_id: Mapped[str] = mapped_column(ForeignKey("assets.id"))
    asset_b_id: Mapped[str] = mapped_column(ForeignKey("assets.id"))
    winner_id: Mapped[str | None] = mapped_column(ForeignKey("assets.id"))
    is_draw: Mapped[bool] = mapped_column(default=False)
    judge: Mapped[str] = mapped_column(default="human")
    judge_reasoning: Mapped[str | None]
    decided_at: Mapped[datetime] = mapped_column(default=func.now())
    is_undone: Mapped[bool] = mapped_column(default=False)

    session: Mapped["RankingSession"] = relationship(back_populates="comparisons")
```

---

#### AugmentationJob / AugmentationResult

```python
class AugmentationJob(Base, TimestampMixin):
    __tablename__ = "augmentation_jobs"

    id: Mapped[str] = mapped_column(primary_key=True)
    project_id: Mapped[str] = mapped_column(ForeignKey("projects.id"))
    job_type: Mapped[str]              # "outpaint" | "background_replace" | "flip" | etc.
    status: Mapped[str] = mapped_column(default="pending")
    provider_id: Mapped[str | None]
    params_json: Mapped[str]           # JSON operation parameters
    total_assets: Mapped[int] = mapped_column(default=0)
    completed_assets: Mapped[int] = mapped_column(default=0)
    error_message: Mapped[str | None]

class AugmentationResult(Base):
    __tablename__ = "augmentation_results"

    id: Mapped[str] = mapped_column(primary_key=True)
    job_id: Mapped[str] = mapped_column(ForeignKey("augmentation_jobs.id"))
    source_asset_id: Mapped[str] = mapped_column(ForeignKey("assets.id"))
    result_asset_id: Mapped[str | None] = mapped_column(ForeignKey("assets.id"))
    # result_asset_id is null if failed
    error: Mapped[str | None]

    source_asset: Mapped["Asset"] = relationship(
        foreign_keys=[source_asset_id],
        back_populates="augmentation_results",
    )
```

---

#### ExportJob

```python
class ExportJob(Base, TimestampMixin):
    __tablename__ = "export_jobs"

    id: Mapped[str] = mapped_column(primary_key=True)
    project_id: Mapped[str] = mapped_column(ForeignKey("projects.id"))
    config_json: Mapped[str]           # Serialized ExportConfig
    status: Mapped[str] = mapped_column(default="pending")
    output_path: Mapped[str | None]
    file_count: Mapped[int] = mapped_column(default=0)
    total_bytes: Mapped[int] = mapped_column(default=0)
    error: Mapped[str | None]

    project: Mapped["Project"] = relationship(back_populates="export_jobs")
```

---

#### ProviderConfig

```python
class ProviderConfig(Base, TimestampMixin):
    __tablename__ = "provider_configs"

    id: Mapped[str] = mapped_column(primary_key=True)
    provider_id: Mapped[str] = mapped_column(unique=True)
    is_enabled: Mapped[bool] = mapped_column(default=True)
    api_key_encrypted: Mapped[str | None]   # OS safeStorage encrypted
    base_url: Mapped[str | None]
    params_json: Mapped[str] = mapped_column(default="{}")
    last_health_check: Mapped[datetime | None]
    last_health_ok: Mapped[bool | None]
```

---

#### UserPreferences

```python
class UserPreferences(Base):
    __tablename__ = "user_preferences"

    id: Mapped[int] = mapped_column(primary_key=True, default=1)
    # Singleton row — always id=1
    theme: Mapped[str] = mapped_column(default="dark")
    default_caption_mode: Mapped[str] = mapped_column(default="detailed")
    default_caption_provider_chain: Mapped[str] = mapped_column(default="caption")
    thumbnail_size: Mapped[int] = mapped_column(default=200)
    grid_columns: Mapped[int] = mapped_column(default=5)
    quality_threshold_hero: Mapped[float] = mapped_column(default=0.8)
    quality_threshold_good: Mapped[float] = mapped_column(default=0.6)
    quality_threshold_discard: Mapped[float] = mapped_column(default=0.3)
    vram_budget_mb: Mapped[int] = mapped_column(default=4096)
    active_project_id: Mapped[str | None]
    onboarding_complete: Mapped[bool] = mapped_column(default=False)
    tours_seen: Mapped[str] = mapped_column(default="[]")  # JSON list of tour IDs
```

---

## 4. MODULE MAP

```
draco_studio/
├── backend/
│   ├── main.py                     # FastAPI app factory, lifespan hooks
│   ├── config.py                   # Settings (Pydantic BaseSettings)
│   ├── database.py                 # Async engine + session factory
│   ├── dependencies.py             # FastAPI Depends() providers
│   │
│   ├── models/                     # SQLAlchemy ORM
│   │   ├── __init__.py
│   │   ├── base.py                 # DeclarativeBase + TimestampMixin
│   │   ├── project.py
│   │   ├── asset.py
│   │   ├── caption.py
│   │   ├── face.py                 # FaceCluster + IdentityCluster
│   │   ├── ranking.py              # RankingSession + RankingComparison
│   │   ├── augmentation.py
│   │   ├── export.py
│   │   └── config.py               # ProviderConfig + UserPreferences
│   │
│   ├── providers/                  # All provider implementations
│   │   ├── base.py                 # BaseProvider ABC
│   │   ├── registry.py             # ProviderRegistry
│   │   ├── vram_manager.py         # VRAM budget manager
│   │   │
│   │   ├── caption/
│   │   │   ├── base.py             # CaptionProvider ABC
│   │   │   ├── florence2.py
│   │   │   ├── ollama.py
│   │   │   ├── gemini.py
│   │   │   ├── openai.py
│   │   │   └── anthropic.py
│   │   │
│   │   ├── face/
│   │   │   ├── detection.py        # FaceDetectionProvider ABC + InsightFace impl
│   │   │   ├── embedding.py        # FaceEmbeddingProvider ABC + ArcFace impl
│   │   │   ├── recognition.py      # FaceRecognitionProvider + Qdrant impl
│   │   │   ├── attributes.py       # FaceAttributeProvider + InsightFace/ONNX impl
│   │   │   ├── head_pose.py        # HeadPoseProvider + InsightFace impl
│   │   │   └── gaze.py             # GazeProvider + L2CS impl
│   │   │
│   │   ├── pose/
│   │   │   ├── base.py             # PoseProvider ABC
│   │   │   ├── mediapipe.py
│   │   │   └── mmpose.py
│   │   │
│   │   ├── embedding/
│   │   │   ├── base.py             # EmbeddingProvider ABC
│   │   │   ├── fastembed.py        # Primary: ONNX CLIP via fastembed
│   │   │   └── clip_torch.py       # Optional: full PyTorch CLIP
│   │   │
│   │   ├── quality/
│   │   │   ├── base.py             # QualityScorer ABC
│   │   │   └── dracoflow.py        # DracoFlowV4QualityScorer
│   │   │
│   │   ├── ranking/
│   │   │   ├── base.py             # RankingEngine ABC
│   │   │   └── openskill.py        # OpenSkillRankingEngine
│   │   │
│   │   ├── duplicate/
│   │   │   ├── base.py             # DuplicateDetectionProvider ABC
│   │   │   ├── phash.py            # Single canonical pHash implementation
│   │   │   └── embedding.py        # Embedding-based dedup via Qdrant
│   │   │
│   │   ├── editing/
│   │   │   ├── image_editor.py     # ImageEditor ABC + Pillow impl
│   │   │   └── outpainting.py      # OutpaintingProvider ABC + impls
│   │   │
│   │   ├── scene/
│   │   │   ├── base.py             # SceneUnderstandingProvider ABC
│   │   │   └── color_variance.py   # Fast deterministic impl (from v5)
│   │   │
│   │   ├── storage/
│   │   │   ├── base.py             # StorageProvider ABC
│   │   │   └── local.py            # LocalStorageProvider
│   │   │
│   │   ├── export/
│   │   │   ├── base.py             # ExportProvider ABC
│   │   │   ├── flat.py
│   │   │   ├── ranked.py
│   │   │   └── huggingface.py
│   │   │
│   │   └── dataset/
│   │       └── balancer.py         # DatasetBalancer
│   │
│   ├── services/                   # Business logic / orchestration
│   │   ├── ingest.py               # Import pipeline (hash → thumbnail → analyze)
│   │   ├── analysis.py             # Coordinate face+quality+embedding for one asset
│   │   ├── clustering.py           # Run HDBSCAN on face embeddings, assign identities
│   │   ├── captioning.py           # Batch caption workflow
│   │   ├── dedup.py                # Duplicate detection pipeline
│   │   ├── ranking.py              # RankingSession lifecycle
│   │   ├── export.py               # Export orchestration
│   │   ├── coach.py                # Dataset analysis + recommendations
│   │   └── thumbnail.py            # Thumbnail generation + cache management
│   │
│   ├── api/                        # FastAPI routers
│   │   ├── health.py               # GET /health, GET /providers/status
│   │   ├── projects.py             # CRUD for projects
│   │   ├── assets.py               # Asset CRUD + bulk operations
│   │   ├── analysis.py             # Trigger analysis jobs
│   │   ├── captions.py             # Caption CRUD + generate + batch
│   │   ├── faces.py                # Face detection + cluster + identity
│   │   ├── ranking.py              # Ranking session + comparison endpoints
│   │   ├── export.py               # Export job endpoints
│   │   ├── augmentation.py         # Image editing + outpainting
│   │   ├── coach.py                # Dataset analysis + recommendations
│   │   ├── providers.py            # Provider config + health check
│   │   └── files.py                # Static file serving (thumbnails, originals)
│   │
│   └── workers/                    # Background task management
│       ├── task_queue.py           # asyncio.Queue + ThreadPoolExecutor wrapper
│       ├── analysis_worker.py      # Dequeues analysis tasks
│       ├── caption_worker.py       # Dequeues caption batch tasks
│       └── export_worker.py        # Dequeues export tasks
│
├── frontend/
│   ├── index.html                  # Vite entry point
│   ├── src/
│   │   ├── main.tsx                # React root + router setup
│   │   ├── theme.css               # Global dark theme CSS variables
│   │   │
│   │   ├── views/                  # Page-level components (one per major workflow)
│   │   │   ├── ProjectView.tsx
│   │   │   ├── GridView.tsx        # Main image grid
│   │   │   ├── CaptionView.tsx     # Caption workflow
│   │   │   ├── FaceView.tsx        # Face clusters + identity
│   │   │   ├── RankingView.tsx     # Arena + pairwise
│   │   │   ├── CoachView.tsx       # Dataset coach
│   │   │   ├── ExportView.tsx
│   │   │   ├── AugmentView.tsx
│   │   │   └── SettingsView.tsx
│   │   │
│   │   ├── components/             # Shared, composable UI components
│   │   │   ├── grid/
│   │   │   │   ├── VirtualGrid.tsx      # react-virtual virtualized grid
│   │   │   │   ├── AssetCard.tsx        # Single image card
│   │   │   │   └── AssetCardSkeleton.tsx
│   │   │   ├── lightbox/
│   │   │   │   ├── Lightbox.tsx
│   │   │   │   └── QualityBreakdown.tsx
│   │   │   ├── caption/
│   │   │   │   ├── CaptionEditor.tsx
│   │   │   │   ├── CaptionHistory.tsx
│   │   │   │   └── CaptionDiff.tsx
│   │   │   ├── face/
│   │   │   │   ├── FaceClusterPanel.tsx
│   │   │   │   └── IdentityCard.tsx
│   │   │   ├── ranking/
│   │   │   │   ├── ArenaView.tsx
│   │   │   │   └── LeaderboardTable.tsx
│   │   │   ├── coach/
│   │   │   │   ├── HealthScore.tsx
│   │   │   │   └── RecommendationCard.tsx
│   │   │   ├── upload/
│   │   │   │   └── DropZone.tsx
│   │   │   ├── providers/
│   │   │   │   ├── ProviderStatusBadge.tsx
│   │   │   │   └── ProviderSelector.tsx
│   │   │   └── shared/
│   │   │       ├── ProgressBar.tsx
│   │   │       ├── Tooltip.tsx
│   │   │       ├── Modal.tsx
│   │   │       └── Kbd.tsx         # Keyboard shortcut display
│   │   │
│   │   ├── stores/                 # Zustand state slices
│   │   │   ├── projectStore.ts     # Current project + project list
│   │   │   ├── assetStore.ts       # Selected assets, filter/sort state
│   │   │   ├── uiStore.ts          # View mode, active panel, modals
│   │   │   ├── rankingStore.ts     # Active session, current pair, undo stack
│   │   │   └── settingsStore.ts    # User preferences + provider config
│   │   │
│   │   ├── hooks/                  # Custom React hooks
│   │   │   ├── useAssets.ts        # TanStack Query wrapper for asset list
│   │   │   ├── useAnalysis.ts      # Trigger + poll analysis jobs
│   │   │   ├── useCaption.ts       # Caption generate + save + history
│   │   │   ├── useThumbnail.ts     # Blob URL management with cleanup
│   │   │   ├── useKeyboard.ts      # Global keyboard shortcut registry
│   │   │   ├── useRanking.ts       # Arena session lifecycle
│   │   │   └── useProviders.ts     # Provider status polling
│   │   │
│   │   ├── providers/              # React context providers
│   │   │   ├── ThemeProvider.tsx
│   │   │   ├── TourProvider.tsx    # Guided tour state
│   │   │   └── QueryProvider.tsx   # TanStack Query client
│   │   │
│   │   ├── api/                    # API client (typed fetch wrappers)
│   │   │   ├── client.ts           # Base fetch with error handling
│   │   │   ├── projects.ts
│   │   │   ├── assets.ts
│   │   │   ├── captions.ts
│   │   │   ├── faces.ts
│   │   │   ├── ranking.ts
│   │   │   └── providers.ts
│   │   │
│   │   └── types/                  # Shared TypeScript types
│   │       ├── asset.ts
│   │       ├── caption.ts
│   │       ├── face.ts
│   │       ├── ranking.ts
│   │       └── provider.ts
│   │
│   └── tours/                      # JSON tour definitions
│       ├── quick_start.json
│       ├── captioning.json
│       └── ranking.json
│
├── electron/
│   ├── main.js                     # Electron entry + window management
│   ├── preload.js                  # Context bridge (minimal — no wizard injection)
│   ├── python-manager.js           # Python env + sidecar lifecycle (from v5, cleaned)
│   └── ipc-handlers.js             # File dialog, tray, auto-updater IPC
│
├── alembic/                        # Database migrations
│   ├── env.py
│   └── versions/
│       └── 001_initial_schema.py
│
├── tests/
│   ├── backend/
│   │   ├── test_providers.py
│   │   ├── test_services.py
│   │   └── test_api.py
│   └── frontend/
│       └── components/
│
├── config/
│   ├── providers.yaml              # Default provider chains
│   └── quality_weights.yaml       # DracoFlow v4 metric weights
│
├── electron-builder.yml
├── package.json
├── vite.config.ts
├── tsconfig.json
└── pyproject.toml                  # Python project config
```

---

## 5. PERFORMANCE ARCHITECTURE

### 5.1 Thumbnail and Image Cache Strategy

**Problem from v5**: All images stored as base64 in JS heap → memory cliff at ~300 images.

**Solution**: Images stay on disk. The frontend only ever holds blob URLs.

```
┌──────────────┐    ┌─────────────────────┐    ┌──────────────────┐
│  Image Grid  │───▶│  useThumbnail hook  │───▶│  Blob URL Pool   │
│  (virtual)   │    │  (per-card)         │    │  (bounded, 500   │
└──────────────┘    └──────────┬──────────┘    │   max URLs)      │
                               │               └──────────────────┘
                               │ cache miss
                               ▼
                    ┌──────────────────────┐
                    │  GET /files/thumb/   │
                    │  {asset_id}          │
                    │  (FastAPI static)    │
                    └──────────┬───────────┘
                               │
                               ▼
                    ┌──────────────────────┐
                    │  Disk thumbnail      │
                    │  ~/.draco/thumbs/    │
                    │  {asset_id}_200.jpg  │
                    └──────────────────────┘
```

**Thumbnail generation** (in `services/thumbnail.py`):
- On ingest: generate 200×200 and 400×400 thumbnails
- Format: JPEG quality 85 — always, regardless of source format
- Written to `{storage_root}/.thumbs/{asset_id}_{size}.jpg`
- Never regenerated if file exists (idempotent)

**Blob URL lifecycle** (`useThumbnail.ts`):
```typescript
// LRU cache of 500 blob URLs max
// On eviction: URL.revokeObjectURL(url) — no memory leak
const cache = new LRUCache<string, string>({ max: 500, dispose: revokeObjectURL })

function useThumbnail(assetId: string) {
  useEffect(() => {
    if (cache.has(assetId)) return
    fetch(`/api/files/thumb/${assetId}`)
      .then(r => r.blob())
      .then(blob => {
        const url = URL.createObjectURL(blob)
        cache.set(assetId, url)
        // trigger re-render
      })
    return () => { /* cache handles revocation */ }
  }, [assetId])
  return cache.get(assetId) ?? null
}
```

---

### 5.2 Virtualized Grid

**Problem from v5**: All image DOM nodes rendered simultaneously → layout thrash and OOM.

**Solution**: `@tanstack/react-virtual` (react-virtual v3).

```typescript
// frontend/src/components/grid/VirtualGrid.tsx

import { useVirtualizer } from '@tanstack/react-virtual'

export function VirtualGrid({ assets }: { assets: Asset[] }) {
  const parentRef = useRef<HTMLDivElement>(null)
  const CARD_SIZE = 220  // px including gap

  const rowVirtualizer = useVirtualizer({
    count: Math.ceil(assets.length / COLUMNS),
    getScrollElement: () => parentRef.current,
    estimateSize: () => CARD_SIZE,
    overscan: 3,  // Render 3 extra rows above/below viewport
  })

  return (
    <div ref={parentRef} style={{ overflow: 'auto', height: '100%' }}>
      <div style={{ height: rowVirtualizer.getTotalSize() }}>
        {rowVirtualizer.getVirtualItems().map(virtualRow => (
          <div key={virtualRow.key} style={{ transform: `translateY(${virtualRow.start}px)` }}>
            {/* Render COLUMNS cards for this row */}
          </div>
        ))}
      </div>
    </div>
  )
}
```

Result: DOM node count stays constant regardless of dataset size. 10,000 images = same performance as 100.

---

### 5.3 VRAM Budget Manager

**Problem from v5**: All GPU models load simultaneously → OOM on 6GB cards.

**Solution**: A `VRAMBudgetManager` that serializes GPU model loading.

```python
# backend/providers/vram_manager.py

import asyncio
from dataclasses import dataclass

@dataclass
class ModelSlot:
    provider_id: str
    vram_mb: int
    loaded: bool = False

class VRAMBudgetManager:
    def __init__(self, budget_mb: int = 4096):
        self.budget_mb = budget_mb
        self._loaded: dict[str, ModelSlot] = {}
        self._lock = asyncio.Lock()

    @property
    def used_mb(self) -> int:
        return sum(s.vram_mb for s in self._loaded.values() if s.loaded)

    @property
    def free_mb(self) -> int:
        return self.budget_mb - self.used_mb

    async def acquire(self, provider: "BaseProvider") -> None:
        """Load provider, evicting others LRU if needed."""
        async with self._lock:
            if provider.provider_id in self._loaded:
                return  # Already loaded

            while self.free_mb < provider.vram_mb and self._loaded:
                # Evict least recently used
                lru_id = next(iter(self._loaded))
                lru_slot = self._loaded.pop(lru_id)
                lru_provider = self._registry.get(lru_id)
                await lru_provider.unload()

            await provider.load()
            self._loaded[provider.provider_id] = ModelSlot(
                provider_id=provider.provider_id,
                vram_mb=provider.vram_mb,
                loaded=True,
            )

    async def release(self, provider_id: str) -> None:
        """Explicit unload (for memory pressure events)."""
        async with self._lock:
            if provider_id in self._loaded:
                del self._loaded[provider_id]
```

**Usage in routes:**
```python
@router.post("/assets/{asset_id}/analyze")
async def analyze_asset(asset_id: str, registry: ProviderRegistry = Depends(get_registry)):
    face_provider = await registry.resolve_chain("face_detection", FaceDetectionProvider)
    await vram_manager.acquire(face_provider)
    result = await face_provider.detect(image_path)
    # Model stays loaded for subsequent requests
```

**VRAM estimates for config:**
| Model | VRAM |
|-------|------|
| InsightFace buffalo_l | 800 MB |
| FastEmbed CLIP (ONNX) | 400 MB |
| Florence-2 base | 1,500 MB |
| Florence-2 large | 2,800 MB |
| LAION aesthetic ONNX | 150 MB |
| L2CS Gaze | 200 MB |
| ONNX Emotion | 100 MB |

Default budget: 4096 MB. At this budget, InsightFace + FastEmbed + Aesthetic fit simultaneously (1,350 MB). Florence-2 base requires evicting others but fits alone.

---

### 5.4 Background Task Queue

```python
# backend/workers/task_queue.py

import asyncio
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from typing import Any, Callable, Coroutine
from enum import Enum

class TaskStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    DONE = "done"
    FAILED = "failed"

@dataclass
class Task:
    id: str
    type: str
    fn: Callable[..., Coroutine]
    args: tuple = field(default_factory=tuple)
    kwargs: dict = field(default_factory=dict)
    status: TaskStatus = TaskStatus.PENDING
    result: Any = None
    error: str | None = None
    progress: float = 0.0  # 0.0-1.0

class TaskQueue:
    def __init__(self, max_concurrent: int = 2, thread_workers: int = 4):
        self._queue: asyncio.Queue[Task] = asyncio.Queue()
        self._tasks: dict[str, Task] = {}
        self._sem = asyncio.Semaphore(max_concurrent)
        self._executor = ThreadPoolExecutor(max_workers=thread_workers)
        self._running = False

    async def submit(self, task: Task) -> str:
        self._tasks[task.id] = task
        await self._queue.put(task)
        return task.id

    def get_status(self, task_id: str) -> Task | None:
        return self._tasks.get(task_id)

    async def start(self):
        self._running = True
        asyncio.create_task(self._worker())

    async def _worker(self):
        while self._running:
            task = await self._queue.get()
            async with self._sem:
                task.status = TaskStatus.RUNNING
                try:
                    task.result = await task.fn(*task.args, **task.kwargs)
                    task.status = TaskStatus.DONE
                except Exception as e:
                    task.status = TaskStatus.FAILED
                    task.error = str(e)
                finally:
                    self._queue.task_done()
```

Progress is polled via `GET /tasks/{task_id}/status` — SSE or WebSocket upgrade is a Phase 3G enhancement.

---

### 5.5 API Key Security

**Problem from v5**: API keys stored as plaintext in localStorage.

**Solution**: Store all keys via the backend using OS-level encryption.

```python
# backend/services/secrets.py

import base64
import os
from cryptography.fernet import Fernet

class SecretsService:
    """
    Primary: Electron safeStorage (OS keychain) via IPC.
    Fallback: AES-256 via cryptography.Fernet with machine-derived key.
    """

    def __init__(self, data_dir: str):
        self._key_path = os.path.join(data_dir, ".keystore")
        self._fernet = self._load_or_create_key()

    def _load_or_create_key(self) -> Fernet:
        if os.path.exists(self._key_path):
            with open(self._key_path, "rb") as f:
                return Fernet(f.read())
        key = Fernet.generate_key()
        with open(self._key_path, "wb") as f:
            f.write(key)
        os.chmod(self._key_path, 0o600)
        return Fernet(key)

    def encrypt(self, plaintext: str) -> str:
        return base64.b64encode(self._fernet.encrypt(plaintext.encode())).decode()

    def decrypt(self, ciphertext: str) -> str:
        return self._fernet.decrypt(base64.b64decode(ciphertext)).decode()
```

The XOR-with-hardcoded-key "encryption" from v5 is completely eliminated.

---

## 6. TESTING STRATEGY

Zero tests exist in v5. The rebuild must establish a test harness from day one.

### Backend
- **Unit tests**: pytest + pytest-asyncio. Test each provider with mock inputs.
- **Integration tests**: Use a real SQLite test DB (`:memory:` async). Spin up a real FastAPI test client.
- **Provider contract tests**: For each provider ABC, a `test_provider_contract.py` that runs the same assertions against any concrete implementation.

### Frontend
- **Component tests**: Vitest + @testing-library/react. Render components with mock API responses.
- **Store tests**: Test Zustand stores in isolation.

### CI
- GitHub Actions: lint (ruff + mypy + eslint), test (pytest + vitest), build (electron-builder) on every push.

---

*This document is the authoritative architecture reference. All implementation decisions must be traced back to a section here or documented as a deviation with justification.*
