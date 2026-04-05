"""
InsightFaceProvider — face detection, recognition, and attribute analysis.
Uses buffalo_l model (ArcFace 512-d + age/gender attributes).
Lazy model loading, ONNX runtime, VRAM-aware.
"""
from __future__ import annotations

import asyncio
import logging
import time
from pathlib import Path
from typing import Any

import numpy as np
from PIL import Image

from config import settings
from providers.base import (
    BoundingBox,
    FaceAnalysisResult,
    FaceDetectionProvider,
    FaceDetectionResult,
)

logger = logging.getLogger(__name__)

try:
    import insightface
    from insightface.app import FaceAnalysis
    _INSIGHTFACE_AVAILABLE = True
except ImportError:
    _INSIGHTFACE_AVAILABLE = False
    logger.warning(
        "insightface not installed — face detection unavailable. "
        "Install with: pip install insightface onnxruntime"
    )

try:
    import cv2
    _CV2_AVAILABLE = True
except ImportError:
    _CV2_AVAILABLE = False


class InsightFaceProvider(FaceDetectionProvider):
    provider_id = "insightface_buffalo_l"
    display_name = "InsightFace buffalo_l (ArcFace)"
    requires_gpu = False   # Runs on CPU via ONNX; set True for GPU mode
    vram_mb = 1200          # Approximate GPU VRAM for buffalo_l

    def __init__(self) -> None:
        self._app: Any | None = None
        self._init_lock = asyncio.Lock()
        self._model_name = settings.INSIGHTFACE_MODEL
        self._ctx_id = settings.INSIGHTFACE_CTX_ID
        self._det_thresh = settings.INSIGHTFACE_DET_THRESH

    async def is_available(self) -> bool:
        return _INSIGHTFACE_AVAILABLE

    async def health_check(self) -> dict[str, Any]:
        t0 = time.monotonic()
        available = await self.is_available()
        return {
            "ok": available,
            "latency_ms": round((time.monotonic() - t0) * 1000, 1),
            "details": {
                "insightface_installed": _INSIGHTFACE_AVAILABLE,
                "model": self._model_name,
                "ctx_id": self._ctx_id,
                "model_loaded": self._app is not None,
            },
        }

    async def load(self) -> None:
        async with self._init_lock:
            if self._app is not None:
                return
            if not _INSIGHTFACE_AVAILABLE:
                logger.error("Cannot load InsightFace — package not installed")
                return

            def _load_model() -> Any:
                app = FaceAnalysis(
                    name=self._model_name,
                    providers=["CUDAExecutionProvider", "CPUExecutionProvider"],
                )
                app.prepare(ctx_id=self._ctx_id, det_thresh=self._det_thresh)
                logger.info(
                    "Loaded InsightFace model '%s' (ctx_id=%d)",
                    self._model_name,
                    self._ctx_id,
                )
                return app

            loop = asyncio.get_event_loop()
            try:
                self._app = await loop.run_in_executor(None, _load_model)
            except Exception as exc:
                logger.error("Failed to load InsightFace: %s", exc)

    async def unload(self) -> None:
        self._app = None
        logger.info("Unloaded InsightFace model")

    async def _ensure_loaded(self) -> bool:
        if self._app is None:
            await self.load()
        return self._app is not None

    # ── FaceDetectionProvider interface ───────────────────────────────────────

    async def detect_faces(self, image_path: str) -> FaceAnalysisResult:
        if not await self._ensure_loaded():
            return FaceAnalysisResult(provider=self.provider_id)

        t0 = time.monotonic()

        def _detect() -> list[Any]:
            img_bgr = self._load_image_bgr(image_path)
            if img_bgr is None:
                return []
            return self._app.get(img_bgr)

        loop = asyncio.get_event_loop()
        raw_faces = await loop.run_in_executor(None, _detect)
        elapsed_ms = round((time.monotonic() - t0) * 1000)

        faces = [self._convert_face(f) for f in raw_faces]

        # Find primary face: largest area with highest det_score
        primary_idx = 0
        if len(faces) > 1:
            def _rank(idx: int) -> float:
                f = faces[idx]
                area = f.bbox.area
                q = f.quality_score or 0.5
                return area * q

            primary_idx = max(range(len(faces)), key=_rank)

        return FaceAnalysisResult(
            faces=faces,
            primary_face_index=primary_idx,
            analysis_time_ms=elapsed_ms,
            provider=self.provider_id,
        )

    async def embed_face(self, face_crop_path: str) -> list[float] | None:
        """Extract ArcFace 512-d embedding from a pre-cropped face image."""
        if not await self._ensure_loaded():
            return None

        def _embed() -> list[float] | None:
            img_bgr = self._load_image_bgr(face_crop_path)
            if img_bgr is None:
                return None
            faces = self._app.get(img_bgr)
            if not faces:
                return None
            emb = faces[0].normed_embedding
            if emb is None:
                return None
            return emb.tolist()

        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(None, _embed)

    async def get_face_embedding_from_bbox(
        self, image_path: str, bbox: BoundingBox
    ) -> list[float] | None:
        """Get face embedding for a specific face in an image."""
        if not await self._ensure_loaded():
            return None

        def _embed() -> list[float] | None:
            img_bgr = self._load_image_bgr(image_path)
            if img_bgr is None:
                return None
            faces = self._app.get(img_bgr)
            if not faces:
                return None
            # Find face closest to the specified bbox
            best_face = None
            best_iou = 0.0
            for f in faces:
                iou = self._compute_iou(f.bbox, bbox)
                if iou > best_iou:
                    best_iou = iou
                    best_face = f
            if best_face is None or best_face.normed_embedding is None:
                return None
            return best_face.normed_embedding.tolist()

        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(None, _embed)

    def compare_embeddings(
        self, emb1: list[float], emb2: list[float]
    ) -> float:
        """Cosine similarity between two face embeddings."""
        a = np.array(emb1, dtype=np.float32)
        b = np.array(emb2, dtype=np.float32)
        norm_a = np.linalg.norm(a)
        norm_b = np.linalg.norm(b)
        if norm_a == 0 or norm_b == 0:
            return 0.0
        return float(np.dot(a, b) / (norm_a * norm_b))

    # ── Private helpers ───────────────────────────────────────────────────────

    def _load_image_bgr(self, image_path: str) -> Any | None:
        """Load image as BGR numpy array (InsightFace native format)."""
        try:
            if _CV2_AVAILABLE:
                img = cv2.imread(image_path)
                if img is None:
                    # Try via PIL for exotic formats
                    pil_img = Image.open(image_path).convert("RGB")
                    img = cv2.cvtColor(np.array(pil_img), cv2.COLOR_RGB2BGR)
                return img
            else:
                pil_img = Image.open(image_path).convert("RGB")
                arr = np.array(pil_img)
                # InsightFace accepts BGR, so reverse the channels
                return arr[:, :, ::-1].copy()
        except Exception as exc:
            logger.warning("Failed to load image %s: %s", image_path, exc)
            return None

    def _convert_face(self, raw: Any) -> FaceDetectionResult:
        """Convert InsightFace face object to our dataclass."""
        # bbox is [x1, y1, x2, y2] from InsightFace
        bbox_arr = getattr(raw, "bbox", None)
        if bbox_arr is not None:
            bbox = BoundingBox(
                x1=float(bbox_arr[0]),
                y1=float(bbox_arr[1]),
                x2=float(bbox_arr[2]),
                y2=float(bbox_arr[3]),
                confidence=float(getattr(raw, "det_score", 0.0)),
            )
        else:
            bbox = BoundingBox(0, 0, 0, 0)

        # Landmarks (5-point: left_eye, right_eye, nose, left_mouth, right_mouth)
        landmarks = None
        if hasattr(raw, "kps") and raw.kps is not None:
            landmarks = raw.kps.tolist()

        # Face embedding (512-d ArcFace)
        embedding = None
        if hasattr(raw, "normed_embedding") and raw.normed_embedding is not None:
            embedding = raw.normed_embedding.tolist()

        # Quality score (det_score from the detection model)
        quality = float(getattr(raw, "det_score", 0.0))

        # Head pose from InsightFace (yaw, pitch, roll if pose model is loaded)
        pose = getattr(raw, "pose", None)
        yaw = pitch = roll = None
        if pose is not None and len(pose) >= 3:
            pitch, yaw, roll = float(pose[0]), float(pose[1]), float(pose[2])

        # Age and gender (buffalo_l includes attribute model)
        age = None
        gender = None
        if hasattr(raw, "age") and raw.age is not None:
            age = float(raw.age)
        if hasattr(raw, "gender") and raw.gender is not None:
            gender = "male" if raw.gender == 1 else "female"

        return FaceDetectionResult(
            bbox=bbox,
            landmarks=landmarks,
            embedding=embedding,
            quality_score=quality,
            pose_yaw=yaw,
            pose_pitch=pitch,
            pose_roll=roll,
            age=age,
            gender=gender,
        )

    @staticmethod
    def _compute_iou(bbox_arr: Any, target: BoundingBox) -> float:
        """Compute IoU between InsightFace bbox array and our BoundingBox."""
        if bbox_arr is None:
            return 0.0
        x1 = float(bbox_arr[0])
        y1 = float(bbox_arr[1])
        x2 = float(bbox_arr[2])
        y2 = float(bbox_arr[3])

        inter_x1 = max(x1, target.x1)
        inter_y1 = max(y1, target.y1)
        inter_x2 = min(x2, target.x2)
        inter_y2 = min(y2, target.y2)

        if inter_x2 <= inter_x1 or inter_y2 <= inter_y1:
            return 0.0

        inter_area = (inter_x2 - inter_x1) * (inter_y2 - inter_y1)
        area1 = (x2 - x1) * (y2 - y1)
        area2 = target.area
        union = area1 + area2 - inter_area
        return inter_area / max(union, 1e-6)
