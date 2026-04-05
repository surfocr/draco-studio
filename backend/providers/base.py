"""
Abstract base classes for ALL providers.
Every provider capability is defined here as an ABC.
No concrete model calls appear in business logic — only provider calls.
"""
from __future__ import annotations

import time
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any


# ══════════════════════════════════════════════════════════════════════════════
# Base Provider
# ══════════════════════════════════════════════════════════════════════════════

class ProviderBase(ABC):
    """Root class for all providers."""

    provider_id: str = ""            # e.g. "insightface_local"
    display_name: str = ""           # e.g. "InsightFace (Local)"
    provider_type: str = ""          # e.g. "face_detection"
    requires_gpu: bool = False
    vram_mb: int = 0                 # Peak VRAM in MB

    @abstractmethod
    async def is_available(self) -> bool:
        """Return True if this provider can accept requests right now."""
        ...

    @abstractmethod
    async def health_check(self) -> dict[str, Any]:
        """Return {"ok": bool, "latency_ms": float, "details": ...}."""
        ...

    async def load(self) -> None:
        """Pre-warm the model. Called by VRAM budget manager."""

    async def unload(self) -> None:
        """Release GPU memory. Called by VRAM budget manager."""


# ══════════════════════════════════════════════════════════════════════════════
# Caption Provider
# ══════════════════════════════════════════════════════════════════════════════

@dataclass
class CaptionResult:
    text: str
    style: str
    confidence: float | None = None
    provider: str = ""
    model: str = ""
    latency_ms: int = 0
    raw: dict[str, Any] | None = None


class CaptionProvider(ProviderBase, ABC):
    provider_type = "caption"

    @abstractmethod
    async def generate(
        self,
        image_path: str,
        style: str = "natural",
        options: dict[str, Any] | None = None,
    ) -> CaptionResult:
        """Generate a single caption for an image."""
        ...

    async def generate_batch(
        self,
        image_paths: list[str],
        style: str = "natural",
        options: dict[str, Any] | None = None,
    ) -> list[CaptionResult]:
        """Generate captions for multiple images. Default: sequential."""
        results = []
        for path in image_paths:
            results.append(await self.generate(path, style, options))
        return results

    def get_prompt_for_style(self, style: str, custom_prompt: str | None = None) -> str:
        """Return the system + user prompt for a given captioning style."""
        prompts: dict[str, str] = {
            "natural": (
                "Describe this image in natural, flowing prose. Include details about "
                "the subject's appearance, expression, clothing, pose, and setting. "
                "Write 2-4 sentences."
            ),
            "concise": (
                "Describe this image concisely in 1-2 sentences. Focus on the main "
                "subject and most notable visual elements."
            ),
            "danbooru_tags": (
                "Generate Danbooru-style tags for this image. Output ONLY comma-separated "
                "tags, no sentences. Include tags for: character features, clothing, "
                "expression, pose, setting, art style, rating. Example format: "
                "1girl, solo, long hair, smile, school uniform, outdoor"
            ),
            "wd_tags": (
                "Generate WD (Waifu Diffusion) style tags. Output ONLY comma-separated "
                "tags ordered by importance. Include: subject count, hair, eyes, outfit, "
                "expression, pose, background, quality tags."
            ),
            "training_literal": (
                "Generate a detailed, literal description suitable for AI training data. "
                "Be specific and objective. Describe: exact poses, clothing details, "
                "facial features, colors, lighting, background elements. "
                "Avoid subjective aesthetic judgements."
            ),
        }
        if custom_prompt:
            return custom_prompt
        return prompts.get(style, prompts["natural"])


# ══════════════════════════════════════════════════════════════════════════════
# Vision Reasoning Provider
# ══════════════════════════════════════════════════════════════════════════════

@dataclass
class VisionReasoningResult:
    answer: str
    reasoning: str | None = None
    confidence: float | None = None
    provider: str = ""
    latency_ms: int = 0


class VisionReasoningProvider(ProviderBase, ABC):
    """For structured queries: ranking judge, dataset coach Q&A, etc."""
    provider_type = "vision_reasoning"

    @abstractmethod
    async def ask(
        self,
        image_paths: list[str],
        question: str,
        system_prompt: str | None = None,
        options: dict[str, Any] | None = None,
    ) -> VisionReasoningResult:
        ...


# ══════════════════════════════════════════════════════════════════════════════
# Embedding Provider
# ══════════════════════════════════════════════════════════════════════════════

@dataclass
class EmbeddingResult:
    vector: list[float]
    dimension: int
    model: str
    provider: str
    latency_ms: int = 0


class EmbeddingProvider(ProviderBase, ABC):
    provider_type = "embedding"

    @abstractmethod
    async def embed_image(self, image_path: str) -> EmbeddingResult:
        ...

    async def embed_batch(self, image_paths: list[str]) -> list[EmbeddingResult]:
        results = []
        for p in image_paths:
            results.append(await self.embed_image(p))
        return results

    @abstractmethod
    async def upsert_embedding(self, asset_id: str, vector: list[float]) -> None:
        ...

    @abstractmethod
    async def search_similar(
        self,
        vector: list[float],
        top_k: int = 10,
        threshold: float = 0.9,
        filter_project_id: str | None = None,
    ) -> list[tuple[str, float]]:
        """Return [(asset_id, score), ...] sorted by descending similarity."""
        ...

    @abstractmethod
    async def delete_embedding(self, asset_id: str) -> None:
        ...


# ══════════════════════════════════════════════════════════════════════════════
# Face Detection Provider
# ══════════════════════════════════════════════════════════════════════════════

@dataclass
class BoundingBox:
    x1: float
    y1: float
    x2: float
    y2: float
    confidence: float = 0.0

    @property
    def width(self) -> float:
        return self.x2 - self.x1

    @property
    def height(self) -> float:
        return self.y2 - self.y1

    @property
    def area(self) -> float:
        return self.width * self.height

    def to_dict(self) -> dict[str, float]:
        return {
            "x1": self.x1, "y1": self.y1,
            "x2": self.x2, "y2": self.y2,
            "confidence": self.confidence,
        }


@dataclass
class FaceDetectionResult:
    bbox: BoundingBox
    landmarks: list[list[float]] | None = None  # 5 or 68 points
    embedding: list[float] | None = None          # 512-d ArcFace embedding
    quality_score: float | None = None            # InsightFace det_score
    pose_yaw: float | None = None
    pose_pitch: float | None = None
    pose_roll: float | None = None
    age: float | None = None
    gender: str | None = None                     # "male"/"female"
    emotion: str | None = None
    gaze_direction: str | None = None


@dataclass
class FaceAnalysisResult:
    faces: list[FaceDetectionResult] = field(default_factory=list)
    primary_face_index: int = 0                   # Index of largest/highest-quality face
    analysis_time_ms: int = 0
    provider: str = ""

    @property
    def primary_face(self) -> FaceDetectionResult | None:
        if not self.faces:
            return None
        return self.faces[self.primary_face_index]

    @property
    def face_count(self) -> int:
        return len(self.faces)


class FaceDetectionProvider(ProviderBase, ABC):
    provider_type = "face_detection"

    @abstractmethod
    async def detect_faces(self, image_path: str) -> FaceAnalysisResult:
        ...

    async def embed_face(self, face_crop_path: str) -> list[float] | None:
        """Extract face embedding from a pre-cropped face image."""
        return None


# ══════════════════════════════════════════════════════════════════════════════
# Face Attribute Provider (separate from detection for modularity)
# ══════════════════════════════════════════════════════════════════════════════

@dataclass
class FaceAttributeResult:
    age: float | None = None
    gender: str | None = None
    emotion: str | None = None
    emotion_scores: dict[str, float] | None = None
    action_units: dict[str, float] | None = None
    gaze_yaw: float | None = None
    gaze_pitch: float | None = None
    eyewear: bool = False
    provider: str = ""


class FaceAttributeProvider(ProviderBase, ABC):
    provider_type = "face_attributes"

    @abstractmethod
    async def analyze_attributes(
        self, image_path: str, face_bbox: BoundingBox | None = None
    ) -> FaceAttributeResult:
        ...


# ══════════════════════════════════════════════════════════════════════════════
# Face Embedding Provider
# ══════════════════════════════════════════════════════════════════════════════

class FaceEmbeddingProvider(ProviderBase, ABC):
    """Abstract provider for extracting face embeddings from images."""
    provider_type = "face_embedding"

    @abstractmethod
    async def embed_face(
        self, image_path: str, face_bbox: BoundingBox | None = None
    ) -> list[float] | None:
        """Return 512-d embedding vector for the face in image_path, or None."""
        ...

    async def embed_batch(
        self, image_paths: list[str]
    ) -> list[list[float] | None]:
        """Embed multiple face images. Default: sequential."""
        results = []
        for p in image_paths:
            results.append(await self.embed_face(p))
        return results


# ══════════════════════════════════════════════════════════════════════════════
# Face Recognition Provider
# ══════════════════════════════════════════════════════════════════════════════

class FaceRecognitionProvider(ProviderBase, ABC):
    provider_type = "face_recognition"

    @abstractmethod
    async def get_embedding(
        self, image_path: str, face_bbox: BoundingBox | None = None
    ) -> list[float] | None:
        """Extract 512-d face embedding."""
        ...

    @abstractmethod
    async def compare_faces(
        self, embedding1: list[float], embedding2: list[float]
    ) -> float:
        """Return cosine similarity between two face embeddings."""
        ...


# ══════════════════════════════════════════════════════════════════════════════
# Head Pose Provider
# ══════════════════════════════════════════════════════════════════════════════

@dataclass
class HeadPoseResult:
    yaw: float       # Left/right rotation in degrees
    pitch: float     # Up/down rotation in degrees
    roll: float      # Head tilt in degrees
    provider: str = ""


class HeadPoseProvider(ProviderBase, ABC):
    provider_type = "head_pose"

    @abstractmethod
    async def estimate_pose(
        self, image_path: str, face_bbox: BoundingBox | None = None
    ) -> HeadPoseResult | None:
        ...


# ══════════════════════════════════════════════════════════════════════════════
# Gaze Provider
# ══════════════════════════════════════════════════════════════════════════════

@dataclass
class GazeResult:
    yaw: float
    pitch: float
    direction_label: str   # "forward"/"left"/"right"/"up"/"down"
    provider: str = ""


class GazeProvider(ProviderBase, ABC):
    provider_type = "gaze"

    @abstractmethod
    async def estimate_gaze(
        self, image_path: str, face_bbox: BoundingBox | None = None
    ) -> GazeResult | None:
        ...


# ══════════════════════════════════════════════════════════════════════════════
# Pose Provider (body pose)
# ══════════════════════════════════════════════════════════════════════════════

@dataclass
class PoseResult:
    keypoints: dict[str, list[float]]   # {"nose": [x, y, conf], "left_shoulder": [...]}
    shot_type: str = "unknown"           # "closeup"/"medium"/"full_body" etc.
    body_pose_type: str | None = None    # "standing"/"sitting"/"lying"
    limb_visibility: dict[str, bool] | None = None
    provider: str = ""


class PoseProvider(ProviderBase, ABC):
    provider_type = "pose"

    @abstractmethod
    async def estimate_pose(self, image_path: str) -> PoseResult | None:
        ...


# ══════════════════════════════════════════════════════════════════════════════
# Action Unit Provider
# ══════════════════════════════════════════════════════════════════════════════

class ActionUnitProvider(ProviderBase, ABC):
    provider_type = "action_units"

    @abstractmethod
    async def detect_action_units(
        self, image_path: str, face_bbox: BoundingBox | None = None
    ) -> dict[str, float]:
        """Return dict of AU code → intensity (0.0–5.0)."""
        ...


# ══════════════════════════════════════════════════════════════════════════════
# Scene Understanding Provider
# ══════════════════════════════════════════════════════════════════════════════

@dataclass
class SceneResult:
    is_indoor: bool | None = None
    scene_class: str | None = None
    scene_tags: list[str] | None = None
    object_tags: list[str] | None = None
    lighting_tags: list[str] | None = None
    background_clutter: float | None = None
    has_plain_background: bool | None = None
    dof_estimate: str | None = None
    provider: str = ""


class SceneUnderstandingProvider(ProviderBase, ABC):
    provider_type = "scene_understanding"

    @abstractmethod
    async def analyze_scene(self, image_path: str) -> SceneResult:
        ...


# ══════════════════════════════════════════════════════════════════════════════
# Quality Scorer
# ══════════════════════════════════════════════════════════════════════════════

@dataclass
class QualityResult:
    # Per-component scores (all 0.0–1.0)
    sharpness: float = 0.0
    resolution: float = 0.0
    brightness: float = 0.0
    contrast: float = 0.0
    saturation: float = 0.0
    noise_estimate: float = 0.0
    aesthetic: float = 0.0
    face_quality: float = 0.0
    face_centering: float = 0.0
    background_score: float = 0.0

    # Composite
    technical_quality: float = 0.0
    composite_score: float = 0.0
    training_usefulness: float = 0.0

    # Breakdown for explanations
    breakdown: dict[str, float] = field(default_factory=dict)
    explanations: dict[str, str] = field(default_factory=dict)
    provider: str = ""


class QualityScorer(ProviderBase, ABC):
    provider_type = "quality"

    @abstractmethod
    async def score_image(
        self,
        image_path: str,
        face_results: FaceAnalysisResult | None = None,
    ) -> QualityResult:
        ...

    @abstractmethod
    async def score(self, image_path: str) -> float:
        """Return a single composite quality score (0.0–1.0)."""
        ...

    @abstractmethod
    async def score_batch(self, image_paths: list) -> list:
        """Return composite quality scores for a list of images."""
        ...


# ══════════════════════════════════════════════════════════════════════════════
# Duplicate Detection Provider
# ══════════════════════════════════════════════════════════════════════════════

@dataclass
class DuplicateCluster:
    cluster_id: str
    cluster_type: str               # "exact"/"phash"/"embedding"/"face"
    asset_ids: list[str]
    representative_id: str          # Keep this one; consider rest redundant
    similarity_scores: dict[str, float] | None = None


class DuplicateDetectionProvider(ProviderBase, ABC):
    provider_type = "duplicate_detection"

    @abstractmethod
    async def find_duplicates(
        self,
        asset_ids: list[str],
        project_id: str,
    ) -> list[DuplicateCluster]:
        ...


# ══════════════════════════════════════════════════════════════════════════════
# Ranking Engine
# ══════════════════════════════════════════════════════════════════════════════

@dataclass
class RatingResult:
    asset_id: str
    mu: float
    sigma: float
    ordinal: float      # mu - 3*sigma (conservative estimate)


class RankingEngine(ProviderBase, ABC):
    provider_type = "ranking"

    @abstractmethod
    async def rate_pair(
        self, winner_id: str, loser_id: str, session_id: str
    ) -> tuple[RatingResult, RatingResult]:
        """Update ratings after a comparison. Returns (winner_new, loser_new)."""
        ...

    @abstractmethod
    async def get_ratings(self, project_id: str) -> list[RatingResult]:
        """Return all ratings sorted by ordinal descending."""
        ...

    @abstractmethod
    async def select_next_pair(self, project_id: str) -> tuple[str, str] | None:
        """Choose the next pair to compare (highest information gain)."""
        ...


# ══════════════════════════════════════════════════════════════════════════════
# Image Editor
# ══════════════════════════════════════════════════════════════════════════════

@dataclass
class EditResult:
    output_path: str
    operation: str
    provider: str
    latency_ms: int = 0


class ImageEditor(ProviderBase, ABC):
    provider_type = "image_editor"

    @abstractmethod
    async def flip_horizontal(self, image_path: str, output_path: str) -> EditResult:
        ...

    @abstractmethod
    async def flip_vertical(self, image_path: str, output_path: str) -> EditResult:
        ...

    @abstractmethod
    async def rotate(
        self, image_path: str, output_path: str, degrees: float
    ) -> EditResult:
        ...

    @abstractmethod
    async def crop(
        self, image_path: str, output_path: str, bbox: BoundingBox
    ) -> EditResult:
        ...

    @abstractmethod
    async def adjust_colors(
        self,
        image_path: str,
        output_path: str,
        brightness: float = 1.0,
        contrast: float = 1.0,
        saturation: float = 1.0,
        hue_shift: float = 0.0,
    ) -> EditResult:
        ...

    @abstractmethod
    async def remove_background(
        self, image_path: str, output_path: str
    ) -> EditResult:
        ...


# ══════════════════════════════════════════════════════════════════════════════
# Outpainting Provider
# ══════════════════════════════════════════════════════════════════════════════

@dataclass
class OutpaintResult:
    output_path: str
    provider: str
    seed: int | None = None
    generation_params: dict[str, Any] | None = None
    latency_ms: int = 0


class OutpaintingProvider(ProviderBase, ABC):
    provider_type = "outpainting"

    @abstractmethod
    async def outpaint(
        self,
        image_path: str,
        output_path: str,
        direction: str,      # "left"/"right"/"up"/"down"/"all"
        padding: int,        # Pixels to add
        prompt: str = "",
        negative_prompt: str = "",
        seed: int | None = None,
    ) -> OutpaintResult:
        ...


# ══════════════════════════════════════════════════════════════════════════════
# Angle Generator
# ══════════════════════════════════════════════════════════════════════════════

@dataclass
class AngleGenerationResult:
    output_path: str
    target_angle: str
    provider: str
    latency_ms: int = 0


class AngleGenerator(ProviderBase, ABC):
    provider_type = "angle_generator"

    @abstractmethod
    async def generate_angle(
        self,
        image_path: str,
        output_path: str,
        target_angle: str,   # "front"/"side"/"three_quarter"/"back"
        prompt: str = "",
    ) -> AngleGenerationResult:
        ...


# ══════════════════════════════════════════════════════════════════════════════
# Dataset Balancer
# ══════════════════════════════════════════════════════════════════════════════

@dataclass
class BalanceReport:
    dimensions: dict[str, dict[str, int]]   # {"shot_type": {"closeup": 12, ...}}
    gaps: list[dict[str, Any]]               # [{"dimension": "shot_type", "missing": "wide"}]
    recommendations: list[str]


class DatasetBalancer(ProviderBase, ABC):
    provider_type = "dataset_balancer"

    @abstractmethod
    async def analyze_balance(
        self, asset_ids: list[str], project_id: str
    ) -> BalanceReport:
        ...


# ══════════════════════════════════════════════════════════════════════════════
# Storage Provider
# ══════════════════════════════════════════════════════════════════════════════

class StorageProvider(ProviderBase, ABC):
    provider_type = "storage"

    @abstractmethod
    async def save_original(
        self, file_bytes: bytes, filename: str, project_id: str
    ) -> str:
        """Save original file. Returns absolute path."""
        ...

    @abstractmethod
    async def get_original(self, asset_path: str) -> bytes:
        ...

    @abstractmethod
    async def save_thumbnail(
        self, image_path: str, asset_id: str, size: int
    ) -> str:
        """Generate + save thumbnail. Returns absolute path."""
        ...

    @abstractmethod
    async def get_thumbnail(self, asset_id: str, size: int) -> bytes | None:
        ...

    @abstractmethod
    async def list_project_files(self, project_id: str) -> list[str]:
        ...

    @abstractmethod
    async def delete_asset(self, asset_path: str, asset_id: str) -> None:
        """Non-destructive delete — moves to .trash/."""
        ...

    @abstractmethod
    async def compute_hashes(self, file_bytes: bytes) -> dict[str, str]:
        """Return {"sha256": str, "phash": str, "dhash": str, "ahash": str}."""
        ...


# ══════════════════════════════════════════════════════════════════════════════
# Export Provider
# ══════════════════════════════════════════════════════════════════════════════

@dataclass
class ExportManifest:
    format: str
    asset_count: int
    output_path: str
    files: list[str]
    metadata: dict[str, Any]


class ExportProvider(ProviderBase, ABC):
    provider_type = "export"

    @abstractmethod
    async def export(
        self,
        asset_ids: list[str],
        output_dir: str,
        options: dict[str, Any] | None = None,
    ) -> ExportManifest:
        ...


# ══════════════════════════════════════════════════════════════════════════════
# Tour Guide Provider
# ══════════════════════════════════════════════════════════════════════════════

@dataclass
class TourStep:
    target_selector: str
    title: str
    content: str
    position: str = "bottom"


class TourGuideProvider(ProviderBase, ABC):
    provider_type = "tour_guide"

    @abstractmethod
    async def get_tour_steps(self, view: str) -> list[TourStep]:
        ...


# ══════════════════════════════════════════════════════════════════════════════
# Image Editing Provider (enhanced)
# ══════════════════════════════════════════════════════════════════════════════

@dataclass
class EditRequest:
    asset_id: str
    operation: str  # "outpaint" | "replace_background" | "change_expression" | "upscale" | "restore" | "inpaint"
    params: dict[str, Any]
    preserve_identity: bool = True
    output_format: str = "png"


@dataclass
class AIEditResult:
    success: bool
    output_path: str
    operation: str
    params_used: dict[str, Any]
    provider: str
    model: str
    latency_ms: int
    identity_preserved: bool | None = None
    before_score: float | None = None
    after_score: float | None = None
    error: str | None = None


@dataclass
class OutpaintRequest:
    asset_id: str
    target_width: int
    target_height: int
    prompt: str | None = None
    negative_prompt: str | None = None
    subject_mask: str | None = None
    steps: int = 30
    strength: float = 0.85


class AIImageEditor(ProviderBase, ABC):
    provider_type = "ai_image_editor"

    @abstractmethod
    async def edit(self, request: EditRequest) -> AIEditResult: ...

    @abstractmethod
    async def get_supported_operations(self) -> list[str]: ...


class AIOutpaintingProvider(ProviderBase, ABC):
    provider_type = "ai_outpainting"

    @abstractmethod
    async def outpaint(self, request: OutpaintRequest) -> AIEditResult: ...

    @abstractmethod
    async def auto_fit_subject(self, asset_id: str, target_width: int, target_height: int) -> AIEditResult: ...
