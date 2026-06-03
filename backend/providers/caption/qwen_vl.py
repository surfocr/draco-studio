"""
Qwen2.5-VL vision-language model caption provider.

Models:
  - Qwen/Qwen2.5-VL-7B-Instruct  (recommended, ~16GB VRAM in fp16)
  - Qwen/Qwen2.5-VL-3B-Instruct  (lighter, ~8GB VRAM)
  - Qwen/Qwen2.5-VL-72B-Instruct (very large, requires significant VRAM/quantization)

Primary use: deep reasoning captions, complex scene understanding, detailed attribute extraction.
"""
from __future__ import annotations
import logging
import time
from typing import Any, Optional

from providers.base import CaptionProvider, CaptionResult

logger = logging.getLogger(__name__)

QWEN_DEFAULT_MODEL = "Qwen/Qwen2.5-VL-7B-Instruct"

STYLE_MESSAGES: dict[str, str] = {
    "training_literal": (
        "Describe this image precisely for use as a LoRA training caption. "
        "Include the subject's physical appearance (hair, eyes, skin, facial features, age), "
        "exact clothing (every item, color, fabric, fit), body pose and hand positions, "
        "facial expression (be specific and literal), background and setting, and lighting. "
        "Be factual. Do not use subjective language."
    ),
    "natural": "Write a natural, detailed description of this image in a readable paragraph.",
    "concise": "Write one concise caption for this image. Maximum 20 words.",
    "danbooru_tags": (
        "Generate Danbooru-style tags for this image. "
        "Output ONLY comma-separated tags: subject count, hair, eyes, expression, outfit, pose, background."
    ),
    "wd_tags": (
        "Generate WD-tagger style tags. Output ONLY comma-separated tags."
    ),
}


class QwenVLProvider(CaptionProvider):
    """Qwen2.5-VL caption provider."""

    provider_id = "qwen_vl"
    display_name = "Qwen 2.5 VL (Local)"
    name = "qwen_vl"
    version = "2.5"

    def __init__(
        self,
        model_id: str = QWEN_DEFAULT_MODEL,
        device: Optional[str] = None,
        max_new_tokens: int = 512,
        temperature: float = 0.7,
        load_in_4bit: bool = False,
    ):
        self.model_id = model_id
        self._requested_device = device
        self.max_new_tokens = max_new_tokens
        self.temperature = temperature
        self.load_in_4bit = load_in_4bit
        self._model = None
        self._processor = None
        self._loaded = False
        self._load_error: Optional[str] = None
        self._device: Optional[str] = None

    async def is_available(self) -> bool:
        try:
            import torch  # noqa
            from transformers import Qwen2_5_VLForConditionalGeneration  # noqa
            return True
        except (ImportError, Exception):
            return False

    async def health_check(self) -> dict[str, Any]:
        return {
            "ok": await self.is_available(),
            "latency_ms": 0,
            "details": {
                "model": self.model_id,
                "loaded": self._loaded,
                "device": self._device or self._requested_device or "unloaded",
                "error": self._load_error,
            },
        }

    def _resolve_device(self) -> str:
        if self._requested_device:
            return self._requested_device
        try:
            import torch
            return "cuda" if torch.cuda.is_available() else "cpu"
        except ImportError:
            return "cpu"

    def _load_model(self) -> bool:
        if self._loaded:
            return True
        if self._load_error:
            return False
        try:
            import torch
            from transformers import Qwen2_5_VLForConditionalGeneration, AutoProcessor

            device = self._resolve_device()
            logger.info(f"Loading Qwen2.5-VL ({self.model_id}) on {device}…")

            dtype = torch.float16 if device == "cuda" else torch.float32
            load_kwargs: dict = {"torch_dtype": dtype}

            if device == "cuda":
                load_kwargs["device_map"] = "auto"

            if self.load_in_4bit and device == "cuda":
                try:
                    from transformers import BitsAndBytesConfig
                    load_kwargs["quantization_config"] = BitsAndBytesConfig(
                        load_in_4bit=True, bnb_4bit_compute_dtype=torch.float16
                    )
                    load_kwargs.pop("torch_dtype", None)
                except ImportError:
                    pass

            self._processor = AutoProcessor.from_pretrained(self.model_id)
            self._model = Qwen2_5_VLForConditionalGeneration.from_pretrained(
                self.model_id, **load_kwargs
            )

            if device not in ("cuda",):
                self._model = self._model.to(device)

            self._model.eval()
            self._device = device
            self._loaded = True
            logger.info("Qwen2.5-VL loaded.")
            return True
        except Exception as exc:
            self._load_error = str(exc)
            logger.error(f"Qwen2.5-VL load failed: {exc}")
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
                error=self._load_error or "Model failed to load",
            )

        opts = options or {}
        t0 = time.monotonic()

        try:
            import torch
            from PIL import Image

            pil_img = Image.open(image_path).convert("RGB")
            user_text = str(opts.get("prompt") or STYLE_MESSAGES.get(style, STYLE_MESSAGES["training_literal"]))

            # Build Qwen chat messages format
            messages = [{
                "role": "user",
                "content": [
                    {"type": "image", "image": pil_img},
                    {"type": "text", "text": user_text},
                ],
            }]

            try:
                from qwen_vl_utils import process_vision_info  # type: ignore[import]
                text_input = self._processor.apply_chat_template(
                    messages, tokenize=False, add_generation_prompt=True
                )
                image_inputs, video_inputs = process_vision_info(messages)
                inputs = self._processor(
                    text=[text_input],
                    images=image_inputs,
                    videos=video_inputs,
                    return_tensors="pt",
                ).to(self._device)
            except ImportError:
                # Fallback: encode image directly without qwen_vl_utils
                import base64
                import io
                buf = io.BytesIO()
                pil_img.save(buf, format="JPEG")
                b64 = base64.b64encode(buf.getvalue()).decode()
                text_only_messages = [{
                    "role": "user",
                    "content": f"<image>data:image/jpeg;base64,{b64}\n{user_text}"
                }]
                text_input = self._processor.apply_chat_template(
                    text_only_messages, tokenize=False, add_generation_prompt=True
                )
                inputs = self._processor(text=text_input, return_tensors="pt").to(self._device)

            with torch.inference_mode():
                output_ids = self._model.generate(
                    **inputs,
                    max_new_tokens=opts.get("max_new_tokens", self.max_new_tokens),
                    temperature=opts.get("temperature", self.temperature),
                    do_sample=True,
                )

            input_len = inputs["input_ids"].shape[1]
            caption = self._processor.batch_decode(
                output_ids[:, input_len:], skip_special_tokens=True
            )[0].strip()

            return CaptionResult(
                text=caption, style=style, confidence=0.92,
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
                del self._model, self._processor
                self._model = self._processor = None
                self._loaded = False
                if torch.cuda.is_available():
                    torch.cuda.empty_cache()
            except Exception:
                pass
