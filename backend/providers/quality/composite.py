"""
CompositeQualityScorer — DracoFlow v4 implementation.
Weights: sharpness(20%), face(20%), aesthetic(15%), brightness(10%),
         contrast(10%), saturation(5%), face_centering(10%), background(5%),
         resolution(5%)
"""
from __future__ import annotations

import asyncio
import logging
import time
from pathlib import Path
from typing import Any

import numpy as np
from PIL import Image, ImageStat

from config import settings
from providers.base import FaceAnalysisResult, QualityResult, QualityScorer

logger = logging.getLogger(__name__)

# Optional: LAION Aesthetic Predictor via ONNX
try:
    import onnxruntime as ort
    _ONNX_AVAILABLE = True
except ImportError:
    _ONNX_AVAILABLE = False

# Optional: OpenCV for Laplacian
try:
    import cv2
    _CV2_AVAILABLE = True
except ImportError:
    _CV2_AVAILABLE = False


class CompositeQualityScorer(QualityScorer):
    provider_id = "composite_quality"
    display_name = "DracoFlow v4 Composite Quality Scorer"

    def __init__(self) -> None:
        self._aesthetic_session: Any | None = None
        self._weights = {
            "sharpness": settings.QUALITY_WEIGHT_SHARPNESS,
            "face_quality": settings.QUALITY_WEIGHT_FACE,
            "aesthetic": settings.QUALITY_WEIGHT_AESTHETIC,
            "brightness": settings.QUALITY_WEIGHT_BRIGHTNESS,
            "contrast": settings.QUALITY_WEIGHT_CONTRAST,
            "saturation": settings.QUALITY_WEIGHT_SATURATION,
            "face_centering": settings.QUALITY_WEIGHT_FACE_CENTER,
            "background": settings.QUALITY_WEIGHT_BACKGROUND,
            "resolution": settings.QUALITY_WEIGHT_RESOLUTION,
        }

    async def is_available(self) -> bool:
        return True  # Always available — uses PIL + numpy fallbacks

    async def health_check(self) -> dict[str, Any]:
        t0 = time.monotonic()
        return {
            "ok": True,
            "latency_ms": round((time.monotonic() - t0) * 1000, 1),
            "details": {
                "cv2_available": _CV2_AVAILABLE,
                "onnx_available": _ONNX_AVAILABLE,
                "aesthetic_model_loaded": self._aesthetic_session is not None,
            },
        }

    # ── Main scoring methods ────────────────────────────────────────────────

    async def score_image(
        self,
        image_path: str,
        face_results: FaceAnalysisResult | None = None,
    ) -> QualityResult:
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(
            None, self._score_sync, image_path, face_results
        )

    async def score(self, image_path: str) -> float:
        result = await self.score_image(image_path)
        return result.composite_score

    async def score_batch(self, image_paths: list) -> list:
        return [await self.score(p) for p in image_paths]

    def _score_sync(
        self,
        image_path: str,
        face_results: FaceAnalysisResult | None,
    ) -> QualityResult:
        t0 = time.monotonic()
        try:
            img = Image.open(image_path).convert("RGB")
        except Exception as exc:
            logger.warning("Could not open image for quality scoring: %s — %s", image_path, exc)
            return QualityResult(provider=self.provider_id)

        img_array = np.array(img)
        w, h = img.width, img.height

        # ── Per-component scores ──────────────────────────────────────────────
        sharpness = self._score_sharpness(img_array)
        resolution = self._score_resolution(w, h)
        brightness, contrast, saturation = self._score_photometric(img, img_array)
        noise_estimate = self._estimate_noise(img_array)
        aesthetic = self._score_aesthetic(img, img_array)

        # Face-dependent scores
        face_quality = 0.5  # neutral default when no face
        face_centering = 0.5
        if face_results and face_results.primary_face:
            pf = face_results.primary_face
            face_quality = self._score_face_quality(pf, w, h)
            face_centering = self._score_face_centering(pf.bbox, w, h)

        background_score = self._score_background(img_array)

        # ── Composite computation ─────────────────────────────────────────────
        components: dict[str, float] = {
            "sharpness": sharpness,
            "face_quality": face_quality,
            "aesthetic": aesthetic,
            "brightness": brightness,
            "contrast": contrast,
            "saturation": saturation,
            "face_centering": face_centering,
            "background": background_score,
            "resolution": resolution,
        }

        # Weighted sum
        composite = sum(
            self._weights.get(k, 0.0) * v for k, v in components.items()
        )
        composite = float(np.clip(composite, 0.0, 1.0))

        # Technical quality = sharpness + resolution + noise (no aesthetic)
        technical = (sharpness * 0.5 + resolution * 0.3 + (1.0 - noise_estimate) * 0.2)
        technical = float(np.clip(technical, 0.0, 1.0))

        # Training usefulness = composite weighted toward face quality + LoRA-specific factors
        # For LoRA training, sharpness and face quality matter most
        training = (
            composite * 0.50
            + face_quality * 0.25
            + sharpness * 0.15
            + resolution * 0.10
        )
        # Penalize images with extreme aspect ratios (LoRA training prefers ~1:1 to ~3:4)
        if w > 0 and h > 0:
            aspect = max(w, h) / min(w, h)
            if aspect > 3.0:
                training *= 0.70  # Stronger penalty for extreme panoramas/banners
            elif aspect > 2.0:
                training *= 0.85  # Mild penalty for very elongated images
        training = float(np.clip(training, 0.0, 1.0))

        explanations = self._build_explanations(components, composite)

        return QualityResult(
            sharpness=round(sharpness, 4),
            resolution=round(resolution, 4),
            brightness=round(brightness, 4),
            contrast=round(contrast, 4),
            saturation=round(saturation, 4),
            noise_estimate=round(noise_estimate, 4),
            aesthetic=round(aesthetic, 4),
            face_quality=round(face_quality, 4),
            face_centering=round(face_centering, 4),
            background_score=round(background_score, 4),
            technical_quality=round(technical, 4),
            composite_score=round(composite, 4),
            training_usefulness=round(training, 4),
            breakdown={k: round(v, 4) for k, v in components.items()},
            explanations=explanations,
            provider=self.provider_id,
        )

    # ── Component scorers ─────────────────────────────────────────────────────

    def _score_sharpness(self, img_array: np.ndarray) -> float:
        """Laplacian variance — higher = sharper."""
        if _CV2_AVAILABLE:
            gray = cv2.cvtColor(img_array, cv2.COLOR_RGB2GRAY)
            lap_var = cv2.Laplacian(gray, cv2.CV_64F).var()
        else:
            # Fallback: manual Laplacian via numpy
            gray = np.mean(img_array, axis=2)
            kernel = np.array([[0, 1, 0], [1, -4, 1], [0, 1, 0]], dtype=np.float32)
            from scipy import ndimage
            try:
                filtered = ndimage.convolve(gray, kernel)
                lap_var = float(np.var(filtered))
            except ImportError:
                # Absolute fallback: edge detection using gradient
                gy = np.diff(gray, axis=0)
                gx = np.diff(gray, axis=1)
                lap_var = float(np.mean(gy**2) + np.mean(gx**2))

        # Normalize: typical sharp images are 100–2000, blurry <50
        # Map 0 → 0.0, 500 → ~0.85, 2000 → 1.0
        score = 1.0 - 1.0 / (1.0 + lap_var / 300.0)
        return float(np.clip(score, 0.0, 1.0))

    def _score_resolution(self, width: int, height: int) -> float:
        """Score based on megapixel count."""
        mp = (width * height) / 1_000_000
        # 0.5 MP → 0.3, 1 MP → 0.55, 2 MP → 0.8, 4+ MP → 1.0
        score = 1.0 - 1.0 / (1.0 + mp * 0.8)
        return float(np.clip(score, 0.0, 1.0))

    def _score_photometric(
        self, img: Image.Image, img_array: np.ndarray
    ) -> tuple[float, float, float]:
        """Return (brightness, contrast, saturation) each 0–1."""
        stat = ImageStat.Stat(img)
        # Brightness: mean of all channels, 128 = ideal
        mean_brightness = float(np.mean(stat.mean)) / 255.0
        brightness_score = 1.0 - abs(mean_brightness - 0.45) * 2.0  # penalise over/under
        brightness_score = float(np.clip(brightness_score, 0.0, 1.0))

        # Contrast: RMS deviation from mean
        rms = float(np.mean(stat.rms)) / 255.0
        contrast_score = float(np.clip(rms * 2.0, 0.0, 1.0))

        # Saturation: convert to HSV, use S channel mean
        img_hsv = img.convert("HSV") if hasattr(img, "convert") else img
        try:
            hsv_array = np.array(img.convert("HSV"))
            sat_mean = float(np.mean(hsv_array[:, :, 1])) / 255.0
            saturation_score = float(np.clip(sat_mean * 1.5, 0.0, 1.0))
        except Exception:
            # Fallback: compute saturation from RGB
            r, g, b = img_array[:, :, 0], img_array[:, :, 1], img_array[:, :, 2]
            max_c = np.maximum(np.maximum(r, g), b).astype(float)
            min_c = np.minimum(np.minimum(r, g), b).astype(float)
            sat = np.where(max_c > 0, (max_c - min_c) / max_c, 0.0)
            saturation_score = float(np.clip(np.mean(sat) * 1.5, 0.0, 1.0))

        return brightness_score, contrast_score, saturation_score

    def _estimate_noise(self, img_array: np.ndarray) -> float:
        """Estimate noise level. Returns 0 = clean, 1 = very noisy."""
        # Estimate using high-frequency residuals
        gray = np.mean(img_array, axis=2).astype(np.float32)
        # Simple estimate: variance of (image - blurred image)
        h, w = gray.shape
        if h < 4 or w < 4:
            return 0.0

        # Use a 3x3 median difference as noise proxy
        kernel_size = 3
        padded = np.pad(gray, kernel_size // 2, mode="reflect")
        noise_map = np.zeros_like(gray)
        for dy in range(kernel_size):
            for dx in range(kernel_size):
                noise_map += np.abs(
                    gray - padded[dy : dy + h, dx : dx + w]
                )
        noise_level = float(np.mean(noise_map)) / (255.0 * kernel_size * kernel_size)
        return float(np.clip(noise_level * 10.0, 0.0, 1.0))

    def _score_aesthetic(
        self, img: Image.Image, img_array: np.ndarray
    ) -> float:
        """
        Aesthetic score. Uses LAION Aesthetic Predictor ONNX model if available,
        else falls back to a heuristic rule-of-thirds / color harmony estimate.
        """
        if self._aesthetic_session is not None:
            return self._aesthetic_onnx(img)
        return self._aesthetic_heuristic(img_array)

    def _aesthetic_heuristic(self, img_array: np.ndarray) -> float:
        """
        Heuristic: score based on dynamic range, color variety, and composition.
        Not as accurate as LAION predictor but requires no model.
        """
        # Dynamic range (gap between brightest and darkest areas)
        gray = np.mean(img_array, axis=2)
        p5 = float(np.percentile(gray, 5))
        p95 = float(np.percentile(gray, 95))
        dynamic_range = (p95 - p5) / 255.0

        # Color variety (std across R, G, B channel means)
        channel_means = [float(np.mean(img_array[:, :, c])) for c in range(3)]
        color_variety = float(np.std(channel_means)) / 128.0

        # Edge density (proxy for detail/interest)
        if _CV2_AVAILABLE:
            gray_uint8 = gray.astype(np.uint8)
            edges = cv2.Canny(gray_uint8, 50, 150)
            edge_density = float(np.mean(edges > 0))
        else:
            gx = np.abs(np.diff(gray, axis=1))
            gy = np.abs(np.diff(gray, axis=0))
            edge_density = float(np.mean(gx) + np.mean(gy)) / 64.0

        score = (
            dynamic_range * 0.4
            + color_variety * 0.3
            + float(np.clip(edge_density * 2.0, 0.0, 1.0)) * 0.3
        )
        return float(np.clip(score, 0.0, 1.0))

    def _aesthetic_onnx(self, img: Image.Image) -> float:
        """Run LAION aesthetic predictor ONNX model."""
        try:
            # Preprocess: resize to 224x224, normalize
            img_resized = img.resize((224, 224), Image.LANCZOS)
            arr = np.array(img_resized).astype(np.float32) / 255.0
            mean = np.array([0.48145466, 0.4578275, 0.40821073])
            std = np.array([0.26862954, 0.26130258, 0.27577711])
            arr = (arr - mean) / std
            arr = arr.transpose(2, 0, 1)[np.newaxis]  # NCHW

            result = self._aesthetic_session.run(None, {"input": arr})
            score = float(result[0][0])
            # LAION predictor outputs 1–10; normalize to 0–1
            return float(np.clip((score - 1.0) / 9.0, 0.0, 1.0))
        except Exception as exc:
            logger.warning("ONNX aesthetic predictor failed: %s", exc)
            return 0.5

    def _score_face_quality(self, face: Any, img_w: int, img_h: int) -> float:
        """Score face quality from InsightFace det_score + face size."""
        det_score = getattr(face, "quality_score", None)
        if det_score is None:
            return 0.5

        # Face coverage: what fraction of image is the face
        bbox = face.bbox
        face_area = bbox.area if hasattr(bbox, "area") else (
            (bbox["x2"] - bbox["x1"]) * (bbox["y2"] - bbox["y1"])
        )
        img_area = img_w * img_h
        face_coverage = face_area / max(img_area, 1)

        # Combine: det_score carries most weight
        score = det_score * 0.7 + min(face_coverage * 4.0, 1.0) * 0.3
        return float(np.clip(score, 0.0, 1.0))

    def _score_face_centering(self, bbox: Any, img_w: int, img_h: int) -> float:
        """Score how centered the primary face is."""
        if hasattr(bbox, "x1"):
            cx = (bbox.x1 + bbox.x2) / 2.0
            cy = (bbox.y1 + bbox.y2) / 2.0
        else:
            cx = (bbox["x1"] + bbox["x2"]) / 2.0
            cy = (bbox["y1"] + bbox["y2"]) / 2.0

        # Normalize to 0–1
        cx_norm = cx / img_w
        cy_norm = cy / img_h

        # Penalise deviation from centre-ish area (0.25–0.75 in each axis)
        cx_score = 1.0 - abs(cx_norm - 0.5) * 2.0
        cy_score = 1.0 - abs(cy_norm - 0.4) * 2.5  # Slightly above center is ideal

        score = (cx_score + cy_score) / 2.0
        return float(np.clip(score, 0.0, 1.0))

    def _score_background(self, img_array: np.ndarray) -> float:
        """
        Score background neutrality by sampling border pixels.
        Inspired by DracoFlow v4 color variance classifier.
        """
        h, w = img_array.shape[:2]
        border_px = 20  # Sample a 20px border

        top = img_array[:border_px, :, :]
        bottom = img_array[-border_px:, :, :]
        left = img_array[:, :border_px, :]
        right = img_array[:, -border_px:, :]

        border = np.concatenate([
            top.reshape(-1, 3),
            bottom.reshape(-1, 3),
            left.reshape(-1, 3),
            right.reshape(-1, 3),
        ])

        # Low variance = neutral/plain background → high score
        variance = float(np.mean(np.var(border, axis=0)))
        # 0 variance = perfect plain, 2000+ = very cluttered
        score = 1.0 / (1.0 + variance / 500.0)
        return float(np.clip(score, 0.0, 1.0))

    def _build_explanations(
        self, components: dict[str, float], composite: float
    ) -> dict[str, str]:
        explanations: dict[str, str] = {}

        def _tier(v: float) -> str:
            if v >= 0.8:
                return "excellent"
            elif v >= 0.6:
                return "good"
            elif v >= 0.4:
                return "fair"
            else:
                return "poor"

        for k, v in components.items():
            tier = _tier(v)
            name = k.replace("_", " ").title()
            if tier == "excellent":
                explanations[k] = f"{name} is excellent ({v:.0%})"
            elif tier == "good":
                explanations[k] = f"{name} is good ({v:.0%})"
            elif tier == "fair":
                explanations[k] = f"{name} is fair ({v:.0%}) — consider improving"
            else:
                explanations[k] = f"{name} is poor ({v:.0%}) — this will hurt training quality"

        if composite >= 0.75:
            explanations["overall"] = "High-quality training image"
        elif composite >= 0.5:
            explanations["overall"] = "Acceptable training image with room for improvement"
        else:
            explanations["overall"] = "Low-quality image — consider excluding from training"

        return explanations

    async def load_aesthetic_model(self, model_path: str) -> None:
        """Optionally load the LAION aesthetic predictor ONNX model."""
        if not _ONNX_AVAILABLE:
            logger.warning("onnxruntime not installed, cannot load aesthetic model")
            return
        if not Path(model_path).exists():
            logger.warning("Aesthetic model not found at %s", model_path)
            return

        def _load() -> Any:
            sess_options = ort.SessionOptions()
            sess_options.graph_optimization_level = ort.GraphOptimizationLevel.ORT_ENABLE_ALL
            return ort.InferenceSession(
                model_path,
                sess_options=sess_options,
                providers=["CUDAExecutionProvider", "CPUExecutionProvider"],
            )

        loop = asyncio.get_event_loop()
        self._aesthetic_session = await loop.run_in_executor(None, _load)
        logger.info("Loaded LAION aesthetic predictor from %s", model_path)
