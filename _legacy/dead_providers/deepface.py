"""
DeepFaceAttributeProvider — stub.
NOT used in default mode (TensorFlow conflict with PyTorch).
InsightFace buffalo_l provides age/gender. This stub exists for future opt-in.
"""
from __future__ import annotations

import logging
from typing import Any

from providers.base import BoundingBox, FaceAttributeProvider, FaceAttributeResult

logger = logging.getLogger(__name__)


class DeepFaceAttributeProvider(FaceAttributeProvider):
    provider_id = "deepface_attributes"
    display_name = "DeepFace Attribute Analysis (Disabled)"

    async def is_available(self) -> bool:
        return False  # Intentionally disabled — TF/PyTorch conflict

    async def health_check(self) -> dict[str, Any]:
        return {
            "ok": False,
            "latency_ms": 0,
            "details": {
                "reason": "DeepFace is disabled to avoid TensorFlow/PyTorch conflict. "
                          "Use InsightFace buffalo_l for age/gender attributes."
            },
        }

    async def analyze_attributes(
        self, image_path: str, face_bbox: BoundingBox | None = None
    ) -> FaceAttributeResult:
        raise NotImplementedError(
            "DeepFace provider is disabled. Use InsightFace buffalo_l instead."
        )
