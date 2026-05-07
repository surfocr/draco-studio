"""
Florence2CaptionProvider — Microsoft Florence-2 via HuggingFace transformers.
Requires: transformers, torch, Pillow
User must explicitly opt-in to trust_remote_code=True.
Tasks mapped to all 5 caption styles. Lazy model loading. Batch support.
"""
from __future__ import annotations

import asyncio
import logging
import time
from typing import Any

from providers.base import CaptionProvider, CaptionResult

logger = logging.getLogger(__name__)

try:
    from transformers import AutoModelForCausalLM, AutoProcessor
    _TRANSFORMERS_AVAILABLE = True
except ImportError:
    _TRANSFORMERS_AVAILABLE = False

# Map caption style → Florence-2 task prompt
FLORENCE2_TASK_MAP: dict[str, str] = {
    "natural": "<MORE_DETAILED_CAPTION>",
    "concise": "<CAPTION>",
    "danbooru_tags": "<DETAILED_CAPTION>",
    "wd_tags": "<DETAILED_CAPTION>",
    "training_literal": "<MORE_DETAILED_CAPTION>",
}

# Post-processing hints per style (tags get comma-joined if list returned)
_TAG_STYLES = {"danbooru_tags", "wd_tags"}


class Florence2CaptionProvider(CaptionProvider):
    provider_id = "florence2"
    display_name = "Florence-2 (Local)"
    requires_gpu = True
    vram_mb = 4096  # float16 large model

    def __init__(
        self,
        model_id: str = "microsoft/Florence-2-large",
        device: str = "auto",
        dtype: str = "float16",
        trust_remote_code: bool = False,
    ) -> None:
        self._model_id = model_id
        self._device = device
        self._dtype = dtype
        self._trust_remote_code = trust_remote_code
        self._model: Any | None = None
        self._processor: Any | None = None
        self._init_lock = asyncio.Lock()

    async def is_available(self) -> bool:
        if not _TRANSFORMERS_AVAILABLE:
            return False
        if not self._trust_remote_code:
            logger.warning(
                "Florence-2 requires trust_remote_code=True. "
                "Enable explicitly in provider config."
            )
            return False
        return True

    async def health_check(self) -> dict[str, Any]:
        available = await self.is_available()
        device = "unknown"
        if _TRANSFORMERS_AVAILABLE:
            import torch
            device = "cuda" if torch.cuda.is_available() else "cpu"
        return {
            "ok": available,
            "latency_ms": 0,
            "details": {
                "model_id": self._model_id,
                "trust_remote_code": self._trust_remote_code,
                "transformers_installed": _TRANSFORMERS_AVAILABLE,
                "model_loaded": self._model is not None,
                "device": device,
            },
        }

    async def load(self) -> None:
        async with self._init_lock:
            if self._model is not None:
                return
            if not await self.is_available():
                return

            def _load() -> tuple[Any, Any]:
                import torch
                dtype = torch.float16 if self._dtype == "float16" else torch.float32
                if self._device == "auto":
                    device = "cuda" if torch.cuda.is_available() else "cpu"
                else:
                    device = self._device
                processor = AutoProcessor.from_pretrained(
                    self._model_id,
                    trust_remote_code=self._trust_remote_code,
                )
                model = AutoModelForCausalLM.from_pretrained(
                    self._model_id,
                    torch_dtype=dtype,
                    trust_remote_code=self._trust_remote_code,
                ).to(device)
                model.eval()
                return model, processor

            loop = asyncio.get_event_loop()
            self._model, self._processor = await loop.run_in_executor(None, _load)
            logger.info("Loaded Florence-2 model: %s", self._model_id)

    def get_prompt_for_style(self, style: str, custom_prompt: str | None = None) -> str:
        # Florence-2 uses task tokens, not natural language prompts
        return FLORENCE2_TASK_MAP.get(style, "<MORE_DETAILED_CAPTION>")

    async def generate(
        self,
        image_path: str,
        style: str = "natural",
        options: dict[str, Any] | None = None,
    ) -> CaptionResult:
        if not self._model or not self._processor:
            await self.load()
        if not self._model:
            return CaptionResult(
                text="", style=style, provider=self.provider_id, model=self._model_id
            )

        opts = options or {}
        task_prompt = FLORENCE2_TASK_MAP.get(style, "<MORE_DETAILED_CAPTION>")
        max_new_tokens = opts.get("max_tokens", 512)

        def _run() -> str:
            from PIL import Image
            import torch
            image = Image.open(image_path).convert("RGB")
            inputs = self._processor(
                text=task_prompt, images=image, return_tensors="pt"
            ).to(next(self._model.parameters()).device)

            with torch.no_grad():
                generated_ids = self._model.generate(
                    input_ids=inputs["input_ids"],
                    pixel_values=inputs["pixel_values"],
                    max_new_tokens=max_new_tokens,
                    do_sample=False,
                )
            generated_text = self._processor.batch_decode(
                generated_ids, skip_special_tokens=False
            )[0]
            parsed = self._processor.post_process_generation(
                generated_text,
                task=task_prompt,
                image_size=(image.width, image.height),
            )
            raw = parsed.get(task_prompt, "")
            # Some tasks return lists (object detection etc.) — join for caption use
            if isinstance(raw, list):
                return ", ".join(str(x) for x in raw).strip()
            return str(raw).strip()

        t0 = time.monotonic()
        loop = asyncio.get_event_loop()
        text = await loop.run_in_executor(None, _run)
        latency_ms = round((time.monotonic() - t0) * 1000)

        return CaptionResult(
            text=text,
            style=style,
            provider=self.provider_id,
            model=self._model_id,
            latency_ms=latency_ms,
        )

    async def generate_batch(
        self,
        image_paths: list[str],
        style: str = "natural",
        options: dict[str, Any] | None = None,
    ) -> list[CaptionResult]:
        """Batch inference — loads all images then runs in a single forward pass."""
        if not self._model or not self._processor:
            await self.load()
        if not self._model:
            return [
                CaptionResult(text="", style=style, provider=self.provider_id, model=self._model_id)
                for _ in image_paths
            ]

        task_prompt = FLORENCE2_TASK_MAP.get(style, "<MORE_DETAILED_CAPTION>")
        opts = options or {}
        max_new_tokens = opts.get("max_tokens", 512)

        def _run_batch() -> list[str]:
            from PIL import Image
            import torch
            images = [Image.open(p).convert("RGB") for p in image_paths]
            inputs = self._processor(
                text=[task_prompt] * len(images),
                images=images,
                return_tensors="pt",
                padding=True,
            ).to(next(self._model.parameters()).device)

            with torch.no_grad():
                generated_ids = self._model.generate(
                    input_ids=inputs["input_ids"],
                    pixel_values=inputs["pixel_values"],
                    max_new_tokens=max_new_tokens,
                    do_sample=False,
                )

            texts = self._processor.batch_decode(generated_ids, skip_special_tokens=False)
            results: list[str] = []
            for raw_text, image in zip(texts, images):
                parsed = self._processor.post_process_generation(
                    raw_text,
                    task=task_prompt,
                    image_size=(image.width, image.height),
                )
                raw = parsed.get(task_prompt, "")
                if isinstance(raw, list):
                    results.append(", ".join(str(x) for x in raw).strip())
                else:
                    results.append(str(raw).strip())
            return results

        t0 = time.monotonic()
        loop = asyncio.get_event_loop()
        texts = await loop.run_in_executor(None, _run_batch)
        total_ms = round((time.monotonic() - t0) * 1000)
        per_ms = total_ms // len(texts) if texts else 0

        return [
            CaptionResult(
                text=text,
                style=style,
                provider=self.provider_id,
                model=self._model_id,
                latency_ms=per_ms,
            )
            for text in texts
        ]
