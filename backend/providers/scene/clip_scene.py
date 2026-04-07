"""CLIP zero-shot scene understanding provider.

Uses OpenAI CLIP ViT-L/14 to classify images against predefined label sets
for scene type, indoor/outdoor, lighting, objects, and background complexity.
No training required — works out of the box with the pretrained CLIP model.
"""
from __future__ import annotations

import logging
import time
from typing import Any, Optional

from providers.base import SceneUnderstandingProvider, SceneResult

logger = logging.getLogger(__name__)

# ── Label banks for zero-shot classification ─────────────────────────────────

SCENE_CLASSES = [
    "portrait", "headshot", "full body shot", "group photo",
    "landscape", "cityscape", "interior room", "studio shot",
    "street photography", "nature scene", "product photo",
    "action shot", "close-up", "macro photography",
    "aerial view", "underwater", "abstract", "still life",
]

INDOOR_OUTDOOR_LABELS = ["indoor scene", "outdoor scene"]

LIGHTING_LABELS = [
    "natural daylight", "golden hour light", "overcast diffused light",
    "harsh direct sunlight", "studio lighting", "artificial indoor lighting",
    "low light or night", "backlit silhouette", "neon or colored lighting",
    "flash photography",
]

OBJECT_LABELS = [
    "person", "face", "hands", "animal", "vehicle", "building",
    "furniture", "food", "plant or tree", "water body",
    "sky", "text or sign", "electronic device", "clothing",
    "artwork", "instrument", "sports equipment", "book",
]

BACKGROUND_LABELS = [
    "plain solid background", "simple gradient background",
    "blurred bokeh background", "cluttered busy background",
    "natural environment background", "urban environment background",
]

DOF_LABELS = [
    "shallow depth of field with blurred background",
    "moderate depth of field",
    "deep depth of field with everything in focus",
]


class CLIPSceneProvider(SceneUnderstandingProvider):
    """CLIP ViT-L/14 zero-shot scene analysis.

    Classifies images against predefined label sets using CLIP's
    zero-shot capability. Provides scene type, indoor/outdoor detection,
    lighting classification, object detection, and background analysis.
    """

    provider_id = "clip_scene"
    display_name = "CLIP Scene Understanding"
    provider_type = "scene_understanding"
    requires_gpu = True
    vram_mb = 1800

    name = "clip_scene"
    version = "ViT-L/14"

    def __init__(self, model_name: str = "ViT-L/14", top_k: int = 5, **kwargs):
        self.model_name = model_name
        self.top_k = top_k
        self._clip_model = None
        self._clip_preprocess = None
        self._device = None
        self._load_error: Optional[str] = None

    async def is_available(self) -> bool:
        try:
            import clip  # noqa: F401
            return True
        except ImportError:
            return False

    def _load(self):
        if self._clip_model is not None or self._load_error:
            return
        try:
            import torch
            import clip

            self._device = "cuda" if torch.cuda.is_available() else "cpu"
            self._clip_model, self._clip_preprocess = clip.load(
                self.model_name, device=self._device
            )
            logger.info("CLIP scene model loaded on %s", self._device)
        except Exception as e:
            self._load_error = str(e)
            logger.error("Failed to load CLIP scene model: %s", e)

    def _classify(self, image, labels: list[str], threshold: float = 0.0) -> list[tuple[str, float]]:
        """Zero-shot classify image against labels. Returns sorted (label, prob) pairs."""
        import torch
        import clip

        text_tokens = clip.tokenize([f"a photo of {label}" for label in labels]).to(self._device)
        image_input = self._clip_preprocess(image).unsqueeze(0).to(self._device)

        with torch.no_grad():
            image_features = self._clip_model.encode_image(image_input)
            text_features = self._clip_model.encode_text(text_tokens)

            image_features = image_features / image_features.norm(dim=-1, keepdim=True)
            text_features = text_features / text_features.norm(dim=-1, keepdim=True)

            similarity = (image_features @ text_features.T).squeeze(0)
            probs = similarity.softmax(dim=-1).cpu().numpy()

        results = [(label, float(prob)) for label, prob in zip(labels, probs)]
        results.sort(key=lambda x: x[1], reverse=True)
        return [(label, prob) for label, prob in results if prob >= threshold]

    async def analyze_scene(self, image_path: str) -> SceneResult:
        """Analyze scene using CLIP zero-shot classification."""
        self._load()
        if self._load_error:
            return SceneResult(provider=self.name)

        try:
            from PIL import Image

            t0 = time.monotonic()
            img = Image.open(image_path).convert("RGB")

            # Scene class
            scene_results = self._classify(img, SCENE_CLASSES)
            scene_class = scene_results[0][0] if scene_results else None
            scene_tags = [label for label, prob in scene_results[:self.top_k] if prob > 0.05]

            # Indoor/outdoor
            io_results = self._classify(img, INDOOR_OUTDOOR_LABELS)
            is_indoor = io_results[0][0] == "indoor scene" if io_results else None

            # Lighting
            lighting_results = self._classify(img, LIGHTING_LABELS)
            lighting_tags = [label for label, prob in lighting_results[:3] if prob > 0.1]

            # Objects
            object_results = self._classify(img, OBJECT_LABELS, threshold=0.08)
            object_tags = [label for label, prob in object_results[:self.top_k]]

            # Background complexity
            bg_results = self._classify(img, BACKGROUND_LABELS)
            top_bg = bg_results[0][0] if bg_results else ""
            has_plain = "plain" in top_bg or "gradient" in top_bg
            # Rough clutter score: higher if cluttered/busy background
            clutter_score = next(
                (prob for label, prob in bg_results if "cluttered" in label), 0.0
            )

            # Depth of field
            dof_results = self._classify(img, DOF_LABELS)
            dof_map = {"shallow": "shallow", "moderate": "moderate", "deep": "deep"}
            dof_estimate = None
            if dof_results:
                for key, val in dof_map.items():
                    if key in dof_results[0][0]:
                        dof_estimate = val
                        break

            latency = int((time.monotonic() - t0) * 1000)
            logger.debug("Scene analysis for %s: %dms", image_path, latency)

            return SceneResult(
                is_indoor=is_indoor,
                scene_class=scene_class,
                scene_tags=scene_tags,
                object_tags=object_tags,
                lighting_tags=lighting_tags,
                background_clutter=round(clutter_score, 3),
                has_plain_background=has_plain,
                dof_estimate=dof_estimate,
                provider=self.name,
            )
        except Exception as e:
            logger.error("Scene analysis failed: %s", e)
            return SceneResult(provider=self.name)

    async def health_check(self) -> dict[str, Any]:
        self._load()
        return {
            "ok": self._load_error is None,
            "provider": self.name,
            "version": self.version,
            "latency_ms": 0,
            "details": {
                "model": self.model_name,
                "device": self._device or "unloaded",
                "error": self._load_error,
            },
        }
