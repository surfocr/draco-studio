"""
GeminiCaptionProvider — Google Gemini Flash/Pro API captioning.
Requires GEMINI_API_KEY environment variable.
Features: rate limiting (10 req/min for flash), retry logic, cost tracking, all 5 styles.
"""
from __future__ import annotations

import asyncio
import base64
import logging
import time
from collections import deque
from pathlib import Path
from typing import Any

import httpx

from config import settings
from providers.base import CaptionProvider, CaptionResult

logger = logging.getLogger(__name__)

GEMINI_API_BASE = "https://generativelanguage.googleapis.com/v1beta"

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

# Rate limits per model (requests per minute)
_RATE_LIMITS: dict[str, int] = {
    "gemini-2.0-flash": 15,
    "gemini-1.5-flash": 15,
    "gemini-1.5-pro": 2,
    "gemini-2.0-flash-exp": 10,
}

_MAX_RETRIES = 3
_RETRY_BACKOFF = [2.0, 4.0, 8.0]

# Input token cost per 1M (approximate, for logging only)
_INPUT_COST_PER_1M: dict[str, float] = {
    "gemini-1.5-flash": 0.075,
    "gemini-2.0-flash": 0.10,
    "gemini-1.5-pro": 3.50,
}


class _RateLimiter:
    """Sliding window rate limiter."""

    def __init__(self, max_per_minute: int) -> None:
        self._max = max_per_minute
        self._timestamps: deque[float] = deque()

    async def acquire(self) -> None:
        while True:
            now = time.monotonic()
            # Remove timestamps older than 60s
            while self._timestamps and now - self._timestamps[0] > 60.0:
                self._timestamps.popleft()
            if len(self._timestamps) < self._max:
                self._timestamps.append(now)
                return
            # Wait until oldest timestamp expires
            wait = 60.0 - (now - self._timestamps[0]) + 0.1
            logger.debug("Gemini rate limit reached, waiting %.1fs", wait)
            await asyncio.sleep(wait)


class GeminiCaptionProvider(CaptionProvider):
    provider_id = "gemini"
    display_name = "Google Gemini (API)"

    def __init__(
        self,
        api_key: str | None = None,
        model: str = "gemini-2.0-flash",
        max_tokens: int = 512,
        temperature: float = 0.3,
    ) -> None:
        self._api_key = api_key or settings.GEMINI_API_KEY
        self._model = model
        self._max_tokens = max_tokens
        self._temperature = temperature
        rpm = _RATE_LIMITS.get(model, 10)
        self._rate_limiter = _RateLimiter(rpm)
        self._total_input_tokens: int = 0

    async def is_available(self) -> bool:
        return bool(self._api_key)

    async def health_check(self) -> dict[str, Any]:
        t0 = time.monotonic()
        if not self._api_key:
            return {
                "ok": False,
                "latency_ms": 0,
                "details": {"error": "GEMINI_API_KEY not configured"},
            }
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                url = f"{GEMINI_API_BASE}/models?key={self._api_key}"
                resp = await client.get(url)
                return {
                    "ok": resp.status_code == 200,
                    "latency_ms": round((time.monotonic() - t0) * 1000, 1),
                    "details": {
                        "model": self._model,
                        "total_input_tokens_used": self._total_input_tokens,
                    },
                }
        except Exception as exc:
            return {
                "ok": False,
                "latency_ms": round((time.monotonic() - t0) * 1000, 1),
                "details": {"error": str(exc)},
            }

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
        if not self._api_key:
            logger.warning("Gemini API key not set")
            return CaptionResult(text="", style=style, provider=self.provider_id, model=self._model)

        opts = options or {}
        model = opts.get("model", self._model)
        max_tokens = opts.get("max_tokens", self._max_tokens)
        temperature = opts.get("temperature", self._temperature)
        prompt_text = self.get_prompt_for_style(style, opts.get("prompt"))

        try:
            with open(image_path, "rb") as f:
                image_bytes = f.read()
            image_b64 = base64.b64encode(image_bytes).decode()
            mime_type = _detect_mime(image_path)
        except Exception as exc:
            logger.error("Failed to read image %s: %s", image_path, exc)
            return CaptionResult(text="", style=style, provider=self.provider_id, model=model)

        payload = {
            "contents": [
                {
                    "parts": [
                        {"inline_data": {"mime_type": mime_type, "data": image_b64}},
                        {"text": prompt_text},
                    ]
                }
            ],
            "generationConfig": {
                "maxOutputTokens": max_tokens,
                "temperature": temperature,
            },
        }

        url = f"{GEMINI_API_BASE}/models/{model}:generateContent?key={self._api_key}"

        last_exc: Exception | None = None
        for attempt in range(_MAX_RETRIES):
            await self._rate_limiter.acquire()
            try:
                t0 = time.monotonic()
                async with httpx.AsyncClient(timeout=60.0) as client:
                    resp = await client.post(url, json=payload)
                    resp.raise_for_status()
                    data = resp.json()

                text = _extract_text(data)
                latency_ms = round((time.monotonic() - t0) * 1000)

                # Log token usage
                usage = data.get("usageMetadata", {})
                input_tokens = usage.get("promptTokenCount", 0)
                self._total_input_tokens += input_tokens
                cost_per_1m = _INPUT_COST_PER_1M.get(model, 0.0)
                approx_cost = input_tokens / 1_000_000 * cost_per_1m
                if input_tokens:
                    logger.debug(
                        "Gemini %s: %d input tokens (~$%.5f)",
                        model, input_tokens, approx_cost,
                    )

                return CaptionResult(
                    text=text,
                    style=style,
                    provider=self.provider_id,
                    model=model,
                    latency_ms=latency_ms,
                    raw={"usage": usage},
                )

            except httpx.HTTPStatusError as exc:
                last_exc = exc
                status_code = exc.response.status_code
                logger.error("Gemini HTTP %d: %s", status_code, exc.response.text[:200])
                if status_code == 429:
                    # Rate limited by server — back off longer
                    await asyncio.sleep(_RETRY_BACKOFF[attempt] * 2)
                    continue
                if status_code < 500:
                    break  # Don't retry client errors
            except Exception as exc:
                last_exc = exc
                logger.error("Gemini attempt %d failed: %s", attempt + 1, exc)

            if attempt < _MAX_RETRIES - 1:
                await asyncio.sleep(_RETRY_BACKOFF[attempt])

        logger.error("Gemini gave up after %d attempts: %s", _MAX_RETRIES, last_exc)
        return CaptionResult(text="", style=style, provider=self.provider_id, model=model)

    async def generate_batch(
        self,
        image_paths: list[str],
        style: str = "natural",
        options: dict[str, Any] | None = None,
    ) -> list[CaptionResult]:
        results: list[CaptionResult] = []
        for path in image_paths:
            result = await self.generate(path, style, options)
            results.append(result)
        return results

    @property
    def total_input_tokens(self) -> int:
        return self._total_input_tokens


def _extract_text(data: dict) -> str:
    try:
        return data["candidates"][0]["content"]["parts"][0]["text"].strip()
    except (KeyError, IndexError):
        return ""


def _detect_mime(image_path: str) -> str:
    ext = Path(image_path).suffix.lower()
    return {
        ".jpg": "image/jpeg",
        ".jpeg": "image/jpeg",
        ".png": "image/png",
        ".webp": "image/webp",
        ".gif": "image/gif",
        ".bmp": "image/bmp",
    }.get(ext, "image/jpeg")
