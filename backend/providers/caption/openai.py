"""
OpenAICaptionProvider — GPT-4o / GPT-4o-mini via OpenAI API.
Requires OPENAI_API_KEY environment variable.
"""
from __future__ import annotations

import base64
import logging
import time
from pathlib import Path
from typing import Any

import httpx

from config import settings
from providers.base import CaptionProvider, CaptionResult

logger = logging.getLogger(__name__)

OPENAI_API_BASE = "https://api.openai.com/v1"


class OpenAICaptionProvider(CaptionProvider):
    provider_id = "openai"
    display_name = "OpenAI GPT-4o (API)"

    def __init__(
        self,
        api_key: str | None = None,
        model: str = "gpt-4o-mini",
        max_tokens: int = 512,
        temperature: float = 0.3,
        base_url: str | None = None,
    ) -> None:
        self._api_key = api_key or settings.OPENAI_API_KEY
        self._model = model
        self._max_tokens = max_tokens
        self._temperature = temperature
        self._base_url = (base_url or OPENAI_API_BASE).rstrip("/")

    async def is_available(self) -> bool:
        return bool(self._api_key)

    async def health_check(self) -> dict[str, Any]:
        t0 = time.monotonic()
        if not self._api_key:
            return {
                "ok": False,
                "latency_ms": 0,
                "details": {"error": "OPENAI_API_KEY not configured"},
            }
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                resp = await client.get(
                    f"{self._base_url}/models",
                    headers={"Authorization": f"Bearer {self._api_key}"},
                )
                return {
                    "ok": resp.status_code == 200,
                    "latency_ms": round((time.monotonic() - t0) * 1000, 1),
                    "details": {"model": self._model},
                }
        except Exception as exc:
            return {
                "ok": False,
                "latency_ms": round((time.monotonic() - t0) * 1000, 1),
                "details": {"error": str(exc)},
            }

    async def generate(
        self,
        image_path: str,
        style: str = "natural",
        options: dict[str, Any] | None = None,
    ) -> CaptionResult:
        if not self._api_key:
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
            mime_type = self._detect_mime(image_path)
        except Exception as exc:
            logger.error("Failed to read image %s: %s", image_path, exc)
            return CaptionResult(text="", style=style, provider=self.provider_id, model=model)

        t0 = time.monotonic()

        payload = {
            "model": model,
            "messages": [
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "image_url",
                            "image_url": {
                                "url": f"data:{mime_type};base64,{image_b64}",
                                "detail": "high",
                            },
                        },
                        {"type": "text", "text": prompt_text},
                    ],
                }
            ],
            "max_tokens": max_tokens,
            "temperature": temperature,
        }

        try:
            async with httpx.AsyncClient(timeout=60.0) as client:
                resp = await client.post(
                    f"{self._base_url}/chat/completions",
                    json=payload,
                    headers={
                        "Authorization": f"Bearer {self._api_key}",
                        "Content-Type": "application/json",
                    },
                )
                resp.raise_for_status()
                data = resp.json()
                text = data["choices"][0]["message"]["content"].strip()
                latency_ms = round((time.monotonic() - t0) * 1000)

                return CaptionResult(
                    text=text,
                    style=style,
                    provider=self.provider_id,
                    model=model,
                    latency_ms=latency_ms,
                    raw=data,
                )
        except httpx.HTTPStatusError as exc:
            logger.error("OpenAI API error %d: %s", exc.response.status_code, exc.response.text[:200])
            return CaptionResult(text="", style=style, provider=self.provider_id, model=model)
        except Exception as exc:
            logger.error("OpenAI caption failed: %s", exc)
            return CaptionResult(text="", style=style, provider=self.provider_id, model=model)

    @staticmethod
    def _detect_mime(image_path: str) -> str:
        ext = Path(image_path).suffix.lower()
        return {
            ".jpg": "image/jpeg", ".jpeg": "image/jpeg",
            ".png": "image/png", ".webp": "image/webp",
            ".gif": "image/gif", ".bmp": "image/bmp",
        }.get(ext, "image/jpeg")
