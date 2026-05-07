"""
Moondream2 ultra-lightweight caption provider.

Model: vikhyatk/moondream2 (~1.8B params, ~2GB, CPU-capable)
Use when: GPU VRAM is limited, or fast rough captioning is needed.
Tradeoff: less detailed than JoyCaption, but runs on nearly any machine.
"""
from __future__ import annotations
import logging
import time
from typing import Any, Optional

from providers.base import CaptionProvider, CaptionResult

logger = logging.getLogger(__name__)

MOONDREAM_MODEL_ID = "vikhyatk/moondream2"
MOONDREAM_REVISION = "2025-01-09"

STYLE_QUESTIONS: dict[str, str] = {
    "training_literal": (
        "Describe this image in detail for training a LoRA model. "
        "Include the subject's appearance, clothing, expression, pose, and background."
    ),
    "natural": "Describe this image in natural language.",
    "concise": "Write a brief one-sentence caption for this image.",
    "danbooru_tags": "List descriptive tags for this image separated by commas.",
    "wd_tags": "List WD-tagger style tags for this image, comma-separated.",
}


class MoondreamProvider(CaptionProvider):
    """Moondream2 lightweight local caption provider."""

    provider_id = "moondream"
    display_name = "Moondream 2 (Local)"
    name = "moondream"
    version = "2"

    def __init__(
        self,
        model_id: str = MOONDREAM_MODEL_ID,
        revision: str = MOONDREAM_REVISION,
    ):
        self.model_id = model_id
        self.revision = revision
        self._model = None
        self._tokenizer = None
        self._loaded = False
        self._load_error: Optional[str] = None

    async def is_available(self) -> bool:
        try:
            import torch  # noqa
            import transformers  # noqa
            return True
        except ImportError:
            return False

    async def health_check(self) -> dict[str, Any]:
        return {
            "ok": await self.is_available(),
            "latency_ms": 0,
            "details": {
                "model": self.model_id,
                "revision": self.revision,
                "loaded": self._loaded,
                "error": self._load_error,
            },
        }

    def _load_model(self) -> bool:
        if self._loaded:
            return True
        if self._load_error:
            return False
        try:
            import torch
            from transformers import AutoModelForCausalLM, AutoTokenizer

            logger.info("Loading Moondream2…")
            self._tokenizer = AutoTokenizer.from_pretrained(
                self.model_id, revision=self.revision
            )
            self._model = AutoModelForCausalLM.from_pretrained(
                self.model_id,
                revision=self.revision,
                trust_remote_code=True,
                torch_dtype=torch.float16 if torch.cuda.is_available() else torch.float32,
            )
            device = "cuda" if torch.cuda.is_available() else "cpu"
            self._model = self._model.to(device)
            self._model.eval()
            self._loaded = True
            logger.info("Moondream2 loaded.")
            return True
        except Exception as exc:
            self._load_error = str(exc)
            logger.error(f"Moondream load failed: {exc}")
            return False

    async def generate(
        self,
        image_path: str,
        style: str = "training_literal",
        options: Optional[dict] = None,
    ) -> CaptionResult:
        if not self._load_model():
            return CaptionResult(
                text="", style=style, confidence=0.0,
                provider=self.name, model=self.model_id, latency_ms=0,
                error=self._load_error,
            )
        t0 = time.monotonic()
        try:
            from PIL import Image
            pil_img = Image.open(image_path).convert("RGB")
            question = STYLE_QUESTIONS.get(style, STYLE_QUESTIONS["training_literal"])
            enc = self._model.encode_image(pil_img)
            caption = self._model.answer_question(enc, question, self._tokenizer)
            return CaptionResult(
                text=caption.strip(), style=style, confidence=0.75,
                provider=self.name, model=self.model_id,
                latency_ms=int((time.monotonic() - t0) * 1000),
            )
        except Exception as exc:
            return CaptionResult(
                text="", style=style, confidence=0.0,
                provider=self.name, model=self.model_id,
                latency_ms=int((time.monotonic() - t0) * 1000),
                error=str(exc),
            )

    async def generate_batch(self, image_paths, style="training_literal", options=None):
        return [await self.generate(p, style, options) for p in image_paths]

    def unload(self) -> None:
        if self._model:
            try:
                import torch
                del self._model, self._tokenizer
                self._model = self._tokenizer = None
                self._loaded = False
                if torch.cuda.is_available():
                    torch.cuda.empty_cache()
            except Exception:
                pass
