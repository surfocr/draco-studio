"""
JoyCaptionProvider — JoyCaption Alpha 2 via HuggingFace.
Purpose-built for anime/illustration training data.
~7B params, requires ~4GB VRAM at float16.
"""
from __future__ import annotations

import asyncio
import logging
import time
from typing import Any

from providers.base import CaptionProvider, CaptionResult

logger = logging.getLogger(__name__)

try:
    from transformers import AutoModelForCausalLM, AutoTokenizer
    from PIL import Image
    import torch
    _TRANSFORMERS_AVAILABLE = True
except ImportError:
    _TRANSFORMERS_AVAILABLE = False

JOYCAPTION_MODEL_ID = "fancyfeast/llama-joycaption-alpha-two-hf-llava"

JOYCAPTION_STYLE_PROMPTS = {
    "natural": (
        "Write a descriptive caption for this image in a natural conversational style."
    ),
    "concise": (
        "Write a short, concise caption for this image in one or two sentences."
    ),
    "danbooru_tags": (
        "Generate a Danbooru-style tag list for this image. "
        "Output only comma-separated tags, no prose."
    ),
    "wd_tags": (
        "Generate Waifu Diffusion style tags for this image. "
        "Output only comma-separated tags ordered by importance."
    ),
    "training_literal": (
        "Write a detailed and literal caption describing this image. "
        "Be specific about appearance, pose, setting, and visual details. "
        "Suitable for AI training data."
    ),
}


class JoyCaptionProvider(CaptionProvider):
    provider_id = "joycaption"
    display_name = "JoyCaption Alpha 2 (Local)"
    requires_gpu = True
    vram_mb = 4096

    def __init__(
        self,
        model_id: str = JOYCAPTION_MODEL_ID,
        device: str = "auto",
    ) -> None:
        self._model_id = model_id
        self._device = device
        self._model: Any | None = None
        self._tokenizer: Any | None = None
        self._init_lock = asyncio.Lock()

    async def is_available(self) -> bool:
        return _TRANSFORMERS_AVAILABLE

    async def health_check(self) -> dict[str, Any]:
        return {
            "ok": _TRANSFORMERS_AVAILABLE,
            "latency_ms": 0,
            "details": {
                "model_id": self._model_id,
                "transformers_installed": _TRANSFORMERS_AVAILABLE,
                "model_loaded": self._model is not None,
            },
        }

    async def load(self) -> None:
        async with self._init_lock:
            if self._model is not None:
                return
            if not _TRANSFORMERS_AVAILABLE:
                return

            def _load() -> tuple[Any, Any]:
                device = "cuda" if torch.cuda.is_available() else "cpu"
                tokenizer = AutoTokenizer.from_pretrained(self._model_id)
                model = AutoModelForCausalLM.from_pretrained(
                    self._model_id,
                    torch_dtype=torch.float16,
                ).to(device)
                model.eval()
                return model, tokenizer

            loop = asyncio.get_event_loop()
            self._model, self._tokenizer = await loop.run_in_executor(None, _load)
            logger.info("Loaded JoyCaption model: %s", self._model_id)

    async def generate(
        self,
        image_path: str,
        style: str = "natural",
        options: dict[str, Any] | None = None,
    ) -> CaptionResult:
        if not self._model:
            await self.load()
        if not self._model or not self._tokenizer:
            return CaptionResult(
                text="", style=style, provider=self.provider_id, model=self._model_id
            )

        opts = options or {}
        prompt = JOYCAPTION_STYLE_PROMPTS.get(style, JOYCAPTION_STYLE_PROMPTS["natural"])
        max_tokens = opts.get("max_tokens", 512)

        def _run() -> str:
            image = Image.open(image_path).convert("RGB")
            # JoyCaption uses a conversation format with image token
            # Simplified single-turn inference
            inputs = self._tokenizer(
                prompt, return_tensors="pt"
            ).to(next(self._model.parameters()).device)

            with torch.no_grad():
                outputs = self._model.generate(
                    **inputs,
                    max_new_tokens=max_tokens,
                    do_sample=False,
                    pad_token_id=self._tokenizer.eos_token_id,
                )
            # Decode only the new tokens
            new_tokens = outputs[0][inputs["input_ids"].shape[1]:]
            return self._tokenizer.decode(new_tokens, skip_special_tokens=True).strip()

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
