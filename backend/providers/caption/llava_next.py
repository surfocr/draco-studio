"""LLaVA-NeXT caption provider — llava-hf/llava-v1.6-mistral-7b-hf."""
from __future__ import annotations
import time
from typing import Optional, List
from providers.base import CaptionProvider, CaptionResult

STYLE_PROMPTS = {
    "training_literal": (
        "Describe this image in precise, literal detail for use as a training caption. "
        "Include subject appearance, clothing, pose, expression, background, and lighting."
    ),
    "natural": "Write a natural, engaging description of this image.",
    "concise": "Describe this image in one or two concise sentences.",
    "danbooru_tags": (
        "List danbooru-style tags for this image separated by commas. "
        "Include: subject descriptors, clothing, hair, eyes, pose, expression, background tags."
    ),
    "wd_tags": (
        "Output WD 1.4 tagger-style tags for this image separated by commas. "
        "Focus on visual attributes: character features, clothing items, pose, setting."
    ),
}

class LLaVANextProvider(CaptionProvider):
    """LLaVA 1.6 (Mistral-7B backbone) caption provider."""

    provider_id = "llava_next"
    display_name = "LLaVA-NeXT (Mistral 7B)"
    provider_type = "caption"
    requires_gpu = True
    vram_mb = 4000

    name = "llava_next"
    version = "v1.6-mistral-7b"

    def __init__(self, model_id: str = "llava-hf/llava-v1.6-mistral-7b-hf",
                 use_4bit: bool = False, max_new_tokens: int = 512, **kwargs):
        self.model_id = model_id
        self.use_4bit = use_4bit
        self.max_new_tokens = max_new_tokens
        self._model = None
        self._processor = None
        self._device = None
        self._load_error: Optional[str] = None

    async def is_available(self) -> bool:
        try:
            import transformers  # noqa: F401
            return True
        except ImportError:
            return False

    def _load(self):
        if self._model is not None or self._load_error:
            return
        try:
            import torch
            from transformers import LlavaNextProcessor, LlavaNextForConditionalGeneration, BitsAndBytesConfig

            self._device = "cuda" if torch.cuda.is_available() else "cpu"
            bnb_cfg = None
            if self.use_4bit and self._device == "cuda":
                bnb_cfg = BitsAndBytesConfig(
                    load_in_4bit=True,
                    bnb_4bit_quant_type="nf4",
                    bnb_4bit_compute_dtype=torch.float16,
                )
            self._processor = LlavaNextProcessor.from_pretrained(self.model_id)
            self._model = LlavaNextForConditionalGeneration.from_pretrained(
                self.model_id,
                quantization_config=bnb_cfg,
                torch_dtype=torch.float16 if self._device == "cuda" else torch.float32,
                device_map="auto" if self._device == "cuda" else None,
                low_cpu_mem_usage=True,
            )
            if self._device != "cuda":
                self._model = self._model.to(self._device)
        except Exception as e:
            self._load_error = str(e)

    async def generate(self, image_path: str, style: str = "training_literal",
                       options: Optional[dict] = None) -> CaptionResult:
        self._load()
        if self._load_error:
            return CaptionResult(
                text="", style=style, confidence=0.0, provider=self.name,
                model=self.model_id, latency_ms=0,
                raw={"error": self._load_error},
            )
        try:
            import torch
            from PIL import Image

            t0 = time.monotonic()
            prompt_text = STYLE_PROMPTS.get(style, STYLE_PROMPTS["training_literal"])
            conversation = [
                {"role": "user", "content": [
                    {"type": "image"},
                    {"type": "text", "text": prompt_text},
                ]},
            ]
            prompt = self._processor.apply_chat_template(conversation, add_generation_prompt=True)
            img = Image.open(image_path).convert("RGB")
            inputs = self._processor(images=img, text=prompt, return_tensors="pt").to(self._device)
            with torch.no_grad():
                output = self._model.generate(**inputs, max_new_tokens=self.max_new_tokens,
                                              do_sample=False)
            # Decode only new tokens
            input_len = inputs["input_ids"].shape[1]
            text = self._processor.decode(output[0][input_len:], skip_special_tokens=True).strip()
            latency = int((time.monotonic() - t0) * 1000)
            return CaptionResult(
                text=text, style=style, confidence=0.9, provider=self.name,
                model=self.model_id, latency_ms=latency,
            )
        except Exception as e:
            return CaptionResult(
                text="", style=style, confidence=0.0, provider=self.name,
                model=self.model_id, latency_ms=0, raw={"error": str(e)},
            )

    async def generate_batch(self, image_paths: List[str], style: str = "training_literal",
                             options: Optional[dict] = None) -> List[CaptionResult]:
        results = []
        for p in image_paths:
            results.append(await self.generate(p, style, options))
        return results

    def unload(self):
        if self._model is not None:
            import torch
            del self._model
            self._model = None
            if torch.cuda.is_available():
                torch.cuda.empty_cache()

    async def health_check(self) -> dict:
        self._load()
        return {
            "provider": self.name,
            "version": self.version,
            "model_id": self.model_id,
            "available": self._load_error is None,
            "device": self._device or "unloaded",
            "use_4bit": self.use_4bit,
            "error": self._load_error,
        }
