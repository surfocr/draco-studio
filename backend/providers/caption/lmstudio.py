"""
LMStudioCaptionProvider — Local LM Studio captioning via OpenAI-compatible API.
Talks to localhost:1234 (default LM Studio server port).
Supports any vision model loaded in LM Studio.
"""
from __future__ import annotations

import base64
import logging
import time
from pathlib import Path
from typing import Any

import httpx

from providers.base import CaptionProvider, CaptionResult

logger = logging.getLogger(__name__)

LMSTUDIO_DEFAULT_BASE = "http://localhost:1234/v1"


class LMStudioCaptionProvider(CaptionProvider):
    provider_id = "lmstudio"
    display_name = "LM Studio (Local)"

    def __init__(
        self,
        api_key: str | None = None,
        model: str | None = None,
        max_tokens: int = 512,
        temperature: float = 0.25,
        base_url: str | None = None,
    ) -> None:
        # LM Studio doesn't require a real API key, but the OpenAI SDK needs one
        self._api_key = api_key or "lm-studio"
        self._model = model  # None means "use whatever model is loaded"
        self._max_tokens = max_tokens
        self._temperature = temperature
        self._base_url = (base_url or LMSTUDIO_DEFAULT_BASE).rstrip("/")

    async def is_available(self) -> bool:
        try:
            async with httpx.AsyncClient(timeout=3.0) as client:
                resp = await client.get(f"{self._base_url}/models")
                return resp.status_code == 200
        except Exception:
            return False

    async def health_check(self) -> dict[str, Any]:
        t0 = time.monotonic()
        try:
            async with httpx.AsyncClient(timeout=5.0) as client:
                resp = await client.get(f"{self._base_url}/models")
                if resp.status_code != 200:
                    return {
                        "ok": False,
                        "latency_ms": round((time.monotonic() - t0) * 1000, 1),
                        "details": {"error": f"HTTP {resp.status_code}"},
                    }
                data = resp.json()
                models = [m.get("id", "?") for m in data.get("data", [])]
                active_model = models[0] if models else self._model
                return {
                    "ok": True,
                    "latency_ms": round((time.monotonic() - t0) * 1000, 1),
                    "details": {
                        "model": active_model,
                        "models_loaded": len(models),
                        "base_url": self._base_url,
                    },
                }
        except Exception as exc:
            return {
                "ok": False,
                "latency_ms": round((time.monotonic() - t0) * 1000, 1),
                "details": {"error": str(exc)},
            }

    async def list_models(self) -> list[dict[str, Any]]:
        """List models currently loaded in LM Studio."""
        try:
            async with httpx.AsyncClient(timeout=5.0) as client:
                resp = await client.get(f"{self._base_url}/models")
                if resp.status_code != 200:
                    return []
                data = resp.json()
                return [
                    {
                        "id": m.get("id", "unknown"),
                        "name": m.get("id", "unknown"),
                        "size": None,
                    }
                    for m in data.get("data", [])
                ]
        except Exception:
            return []

    async def generate(
        self,
        image_path: str,
        style: str = "natural",
        options: dict[str, Any] | None = None,
    ) -> CaptionResult:
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
            return CaptionResult(
                text="", style=style, provider=self.provider_id, model=model or ""
            )

        # If no model specified, try to detect the loaded model
        if not model:
            model = await self._detect_loaded_model()

        t0 = time.monotonic()

        payload: dict[str, Any] = {
            "messages": [
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "image_url",
                            "image_url": {
                                "url": f"data:{mime_type};base64,{image_b64}",
                            },
                        },
                        {"type": "text", "text": prompt_text},
                    ],
                }
            ],
            "max_tokens": max_tokens,
            "temperature": temperature,
            "stream": False,
        }
        if model:
            payload["model"] = model

        try:
            async with httpx.AsyncClient(timeout=120.0) as client:
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
                used_model = data.get("model", model or "lmstudio")

                return CaptionResult(
                    text=text,
                    style=style,
                    provider=self.provider_id,
                    model=used_model,
                    latency_ms=latency_ms,
                    raw=data,
                )
        except httpx.HTTPStatusError as exc:
            logger.error(
                "LM Studio API error %d: %s",
                exc.response.status_code,
                exc.response.text[:200],
            )
            return CaptionResult(
                text="", style=style, provider=self.provider_id, model=model or ""
            )
        except Exception as exc:
            logger.error("LM Studio caption failed: %s", exc)
            return CaptionResult(
                text="", style=style, provider=self.provider_id, model=model or ""
            )

    async def _detect_loaded_model(self) -> str | None:
        """Try to detect the currently loaded model in LM Studio."""
        try:
            async with httpx.AsyncClient(timeout=3.0) as client:
                resp = await client.get(f"{self._base_url}/models")
                if resp.status_code == 200:
                    data = resp.json()
                    models = data.get("data", [])
                    if models:
                        return models[0].get("id")
        except Exception:
            pass
        return None

    @staticmethod
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
