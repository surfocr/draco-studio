"""
OllamaCaptionProvider — full Ollama local VLM captioning provider.
Talks to localhost:11434 (or configured OLLAMA_BASE_URL).
Supports any vision model the user has pulled (llava, moondream, qwen2.5-vl, etc.)
Features: retry logic (3 attempts + backoff), streaming mode, configurable batch_size.
"""
from __future__ import annotations

import asyncio
import base64
import json
import logging
import time
from typing import Any

import httpx

from config import settings
from providers.base import CaptionProvider, CaptionResult

logger = logging.getLogger(__name__)

STYLE_PROMPTS: dict[str, str] = {
    "natural": (
        "Describe this image in natural language. Be specific about the person's "
        "appearance, expression, clothing, pose, and background setting."
    ),
    "concise": (
        "Write a concise image caption for CLIP/T5 training. Focus on the most "
        "important visual elements. Keep it under 77 tokens."
    ),
    "danbooru_tags": (
        "List Danbooru-style tags for this image. Output only comma-separated tags "
        "in order of importance. Include: character features, expression, clothing, "
        "action, background, art style if applicable."
    ),
    "wd_tags": (
        "Generate WD-tagger style tags. Output comma-separated tags focusing on: "
        "1girl/1boy, hair color/style, eye color, expression, outfit, pose, "
        "background, rating."
    ),
    "training_literal": (
        "Write a literal training caption describing exactly what is visible: "
        "subject's physical features, precise clothing description, exact pose/gesture, "
        "facial expression, background elements, lighting. This will be used directly "
        "as a LoRA training caption."
    ),
}

_MAX_RETRIES = 3
_RETRY_BACKOFF = [1.0, 2.0, 4.0]


class OllamaCaptionProvider(CaptionProvider):
    provider_id = "ollama"
    display_name = "Ollama (Local VLM)"

    def __init__(
        self,
        base_url: str | None = None,
        model: str = "llava:13b",
        temperature: float = 0.3,
        context_length: int = 4096,
        max_tokens: int = 512,
        timeout: int | None = None,
        batch_size: int = 1,
        stream: bool = False,
    ) -> None:
        self._base_url = (base_url or settings.OLLAMA_BASE_URL).rstrip("/")
        self._model = model
        self._temperature = temperature
        self._context_length = context_length
        self._max_tokens = max_tokens
        self._timeout = timeout or settings.OLLAMA_TIMEOUT
        self._batch_size = batch_size
        self._stream = stream

    # ── ProviderBase ──────────────────────────────────────────────────────────

    async def is_available(self) -> bool:
        try:
            async with httpx.AsyncClient(timeout=5.0) as client:
                resp = await client.get(f"{self._base_url}/api/version")
                return resp.status_code == 200
        except Exception:
            return False

    async def health_check(self) -> dict[str, Any]:
        t0 = time.monotonic()
        try:
            async with httpx.AsyncClient(timeout=5.0) as client:
                resp = await client.get(f"{self._base_url}/api/tags")
                ok = resp.status_code == 200
                models: list[str] = []
                if ok:
                    data = resp.json()
                    models = [m["name"] for m in data.get("models", [])]
                return {
                    "ok": ok,
                    "latency_ms": round((time.monotonic() - t0) * 1000, 1),
                    "details": {
                        "base_url": self._base_url,
                        "current_model": self._model,
                        "available_models": models,
                    },
                }
        except Exception as exc:
            return {
                "ok": False,
                "latency_ms": round((time.monotonic() - t0) * 1000, 1),
                "details": {"error": str(exc)},
            }

    # ── CaptionProvider ───────────────────────────────────────────────────────

    def get_prompt_for_style(self, style: str, custom_prompt: str | None = None) -> str:
        if custom_prompt:
            return custom_prompt
        return STYLE_PROMPTS.get(style, STYLE_PROMPTS["natural"])

    async def generate(
        self,
        image_path: str,
        style: str = "natural",
        options: dict[str, Any] | None = None,
    ) -> CaptionResult:
        opts = options or {}
        model = opts.get("model", self._model)
        temperature = opts.get("temperature", self._temperature)
        max_tokens = opts.get("max_tokens", self._max_tokens)
        context_length = opts.get("context_length", self._context_length)
        use_stream = opts.get("stream", self._stream)
        prompt_text = self.get_prompt_for_style(style, opts.get("prompt"))

        try:
            image_b64 = _encode_image(image_path)
        except Exception as exc:
            logger.error("Failed to encode image %s: %s", image_path, exc)
            return CaptionResult(text="", style=style, provider=self.provider_id, model=model)

        payload: dict[str, Any] = {
            "model": model,
            "prompt": prompt_text,
            "images": [image_b64],
            "stream": use_stream,
            "options": {
                "temperature": temperature,
                "num_predict": max_tokens,
                "num_ctx": context_length,
            },
        }

        last_exc: Exception | None = None
        for attempt in range(_MAX_RETRIES):
            try:
                t0 = time.monotonic()
                if use_stream:
                    text = await self._generate_streaming(payload)
                else:
                    text = await self._generate_nonstreaming(payload)
                latency_ms = round((time.monotonic() - t0) * 1000)
                return CaptionResult(
                    text=text,
                    style=style,
                    provider=self.provider_id,
                    model=model,
                    latency_ms=latency_ms,
                )
            except httpx.TimeoutException as exc:
                last_exc = exc
                logger.warning("Ollama timeout (attempt %d/%d) for %s", attempt + 1, _MAX_RETRIES, image_path)
            except httpx.HTTPStatusError as exc:
                last_exc = exc
                logger.error("Ollama HTTP %d: %s", exc.response.status_code, exc.response.text[:200])
                if exc.response.status_code < 500:
                    break
            except Exception as exc:
                last_exc = exc
                logger.error("Ollama attempt %d failed: %s", attempt + 1, exc)

            if attempt < _MAX_RETRIES - 1:
                await asyncio.sleep(_RETRY_BACKOFF[attempt])

        logger.error("Ollama gave up after %d attempts: %s", _MAX_RETRIES, last_exc)
        return CaptionResult(text="", style=style, provider=self.provider_id, model=model)

    async def _generate_nonstreaming(self, payload: dict) -> str:
        async with httpx.AsyncClient(timeout=self._timeout) as client:
            resp = await client.post(f"{self._base_url}/api/generate", json=payload)
            resp.raise_for_status()
            return resp.json().get("response", "").strip()

    async def _generate_streaming(self, payload: dict) -> str:
        chunks: list[str] = []
        stream_payload = {**payload, "stream": True}
        async with httpx.AsyncClient(timeout=self._timeout) as client:
            async with client.stream("POST", f"{self._base_url}/api/generate", json=stream_payload) as resp:
                resp.raise_for_status()
                async for line in resp.aiter_lines():
                    if not line:
                        continue
                    try:
                        data = json.loads(line)
                        chunks.append(data.get("response", ""))
                        if data.get("done"):
                            break
                    except Exception:
                        continue
        return "".join(chunks).strip()

    async def generate_batch(
        self,
        image_paths: list[str],
        style: str = "natural",
        options: dict[str, Any] | None = None,
    ) -> list[CaptionResult]:
        """Process in batches of self._batch_size (Ollama is sequential per request)."""
        results: list[CaptionResult] = []
        bs = max(1, self._batch_size)
        for i in range(0, len(image_paths), bs):
            chunk = image_paths[i : i + bs]
            for path in chunk:
                result = await self.generate(path, style, options)
                results.append(result)
        return results

    async def list_models(self) -> list[dict[str, Any]]:
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                resp = await client.get(f"{self._base_url}/api/tags")
                resp.raise_for_status()
                return resp.json().get("models", [])
        except Exception as exc:
            logger.warning("Could not list Ollama models: %s", exc)
            return []

    async def list_vision_models(self) -> list[str]:
        models = await self.list_models()
        vision_indicators = [
            "llava", "moondream", "bakllava", "obsidian", "minicpm",
            "qwen2.5-vl", "qwen-vl", "cogvlm", "internvl", "phi3-vision",
            "llama3.2-vision", "granite3.2-vision",
        ]
        return [
            m["name"] for m in models
            if any(ind in m.get("name", "").lower() for ind in vision_indicators)
        ]

    def set_model(self, model: str) -> None:
        self._model = model


def _encode_image(image_path: str) -> str:
    with open(image_path, "rb") as f:
        return base64.b64encode(f.read()).decode("utf-8")
