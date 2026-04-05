"""
AIJudge — Multi-dimensional AI scoring and comparison for ML training images.

Uses vision-capable LLM (Gemini, Ollama) to score images on 8 quality dimensions
and compare pairs. Returns structured JSON with scores + explanations.
Falls back to heuristic scoring from existing analysis data if AI is unavailable.
"""
from __future__ import annotations

import base64
import json
import logging
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

_SCORE_PROMPT = """Analyze this image for use in a machine learning training dataset.

Score each dimension from 0.0 to 1.0 and provide brief reasoning.

Respond with ONLY valid JSON:
{
    "technical_quality": {"score": 0.0, "reason": ""},
    "aesthetic_quality": {"score": 0.0, "reason": ""},
    "face_clarity": {"score": 0.0, "reason": "", "not_applicable": false},
    "pose_usefulness": {"score": 0.0, "reason": ""},
    "expression_quality": {"score": 0.0, "reason": "", "not_applicable": false},
    "background_usefulness": {"score": 0.0, "reason": ""},
    "uniqueness": {"score": 0.0, "reason": ""},
    "training_value": {"score": 0.0, "reason": ""},
    "composite": {"score": 0.0},
    "strengths": [""],
    "weaknesses": [""],
    "recommendation": "keep",
    "confidence": "high",
    "needs_human_review": false,
    "review_reason": ""
}"""

_COMPARE_PROMPT = """Compare these two images for use in a machine learning training dataset.
Image A is the first image, Image B is the second image.

Respond with ONLY valid JSON:
{
    "winner": "A",
    "confidence": "high",
    "margin": "clear",
    "technical_quality": {"winner": "A", "reason": ""},
    "aesthetic_quality": {"winner": "A", "reason": ""},
    "face_clarity": {"winner": "A", "reason": ""},
    "overall_reasoning": "",
    "A_strengths": [""],
    "B_strengths": [""],
    "dataset_contribution": {
        "A": "",
        "B": ""
    }
}"""


@dataclass
class AIJudgeScore:
    score: float
    reason: str = ""
    not_applicable: bool = False


@dataclass
class AIJudgeResult:
    asset_id: str
    technical_quality: AIJudgeScore = field(default_factory=lambda: AIJudgeScore(0.5))
    aesthetic_quality: AIJudgeScore = field(default_factory=lambda: AIJudgeScore(0.5))
    face_clarity: AIJudgeScore = field(default_factory=lambda: AIJudgeScore(0.5))
    pose_usefulness: AIJudgeScore = field(default_factory=lambda: AIJudgeScore(0.5))
    expression_quality: AIJudgeScore = field(default_factory=lambda: AIJudgeScore(0.5))
    background_usefulness: AIJudgeScore = field(default_factory=lambda: AIJudgeScore(0.5))
    uniqueness: AIJudgeScore = field(default_factory=lambda: AIJudgeScore(0.5))
    training_value: AIJudgeScore = field(default_factory=lambda: AIJudgeScore(0.5))
    composite: float = 0.5
    strengths: list[str] = field(default_factory=list)
    weaknesses: list[str] = field(default_factory=list)
    recommendation: str = "maybe"   # "keep" | "maybe" | "remove"
    confidence: str = "low"          # "high" | "medium" | "low"
    needs_human_review: bool = False
    review_reason: str = ""
    provider_used: str = ""
    is_fallback: bool = False


@dataclass
class AIJudgeComparisonResult:
    asset_id_a: str
    asset_id_b: str
    winner: str          # "A" | "B" | "draw"
    winner_asset_id: str
    confidence: str      # "high" | "medium" | "low"
    margin: str          # "clear" | "slight" | "negligible"
    technical_quality: dict[str, str] = field(default_factory=dict)
    aesthetic_quality: dict[str, str] = field(default_factory=dict)
    face_clarity: dict[str, str] = field(default_factory=dict)
    overall_reasoning: str = ""
    a_strengths: list[str] = field(default_factory=list)
    b_strengths: list[str] = field(default_factory=list)
    dataset_contribution: dict[str, str] = field(default_factory=dict)
    provider_used: str = ""


class AIJudge:
    """Multi-dimensional AI scoring with structured JSON output."""

    def __init__(self, provider_name: str = "auto") -> None:
        self._provider_name = provider_name

    async def score_image(
        self,
        image_path: str,
        asset_id: str,
        existing_analysis: dict[str, Any] | None = None,
    ) -> AIJudgeResult:
        """Score a single image. Falls back to heuristic if AI unavailable."""
        provider = await self._get_provider()

        if provider is None:
            logger.debug("No AI provider available — using heuristic fallback for %s", asset_id)
            return self._fallback_score(asset_id, image_path, existing_analysis or {})

        try:
            response = await self._call_provider(provider, _SCORE_PROMPT, [image_path])
            parsed = self._parse_score_response(response)
            return self._build_score_result(asset_id, parsed, provider_name=self._get_provider_id(provider))
        except Exception as exc:
            logger.warning("AI judge score failed (%s): %s — using fallback", asset_id, exc)
            return self._fallback_score(asset_id, image_path, existing_analysis or {})

    async def compare_images(
        self,
        image_path_a: str,
        asset_id_a: str,
        image_path_b: str,
        asset_id_b: str,
    ) -> AIJudgeComparisonResult:
        provider = await self._get_provider()

        if provider is None:
            # Fallback: call score on each and compare composites
            return self._fallback_compare(asset_id_a, asset_id_b, {}, {})

        try:
            response = await self._call_provider(provider, _COMPARE_PROMPT, [image_path_a, image_path_b])
            parsed = self._parse_compare_response(response)
            return self._build_compare_result(
                asset_id_a, asset_id_b, parsed,
                provider_name=self._get_provider_id(provider),
            )
        except Exception as exc:
            logger.warning("AI judge compare failed: %s — using fallback", exc)
            return self._fallback_compare(asset_id_a, asset_id_b, {}, {})

    async def _get_provider(self) -> Any | None:
        from providers.registry import get_registry
        registry = get_registry()

        if self._provider_name != "auto":
            p = registry.get("caption", self._provider_name)
            if p and await p.is_available():
                return p
            return None

        # Auto: try gemini first (best vision), then ollama
        for pid in ("gemini", "ollama"):
            p = registry.get("caption", pid)
            if p and await p.is_available():
                return p
        return None

    def _get_provider_id(self, provider: Any) -> str:
        return getattr(provider, "provider_id", "unknown")

    async def _call_provider(self, provider: Any, prompt: str, image_paths: list[str]) -> str:
        """Call a caption provider with a structured prompt and one or more images."""
        pid = self._get_provider_id(provider)

        if pid == "gemini":
            return await self._call_gemini(provider, prompt, image_paths)
        elif pid == "ollama":
            return await self._call_ollama(provider, prompt, image_paths)
        else:
            # Generic: use first image
            result = await provider.generate(image_paths[0], "natural", {"prompt": prompt})
            return result.text

    async def _call_gemini(self, provider: Any, prompt: str, image_paths: list[str]) -> str:
        import httpx
        api_key = provider._api_key
        model = provider._model
        parts: list[dict] = []
        for path in image_paths:
            with open(path, "rb") as f:
                data = base64.b64encode(f.read()).decode()
            ext = Path(path).suffix.lower()
            mime = {".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".png": "image/png", ".webp": "image/webp"}.get(ext, "image/jpeg")
            parts.append({"inline_data": {"mime_type": mime, "data": data}})
        parts.append({"text": prompt})

        payload = {
            "contents": [{"parts": parts}],
            "generationConfig": {"maxOutputTokens": 1024, "temperature": 0.1},
        }
        url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={api_key}"
        async with httpx.AsyncClient(timeout=60.0) as client:
            resp = await client.post(url, json=payload)
            resp.raise_for_status()
            data = resp.json()
        try:
            return data["candidates"][0]["content"]["parts"][0]["text"].strip()
        except (KeyError, IndexError):
            return ""

    async def _call_ollama(self, provider: Any, prompt: str, image_paths: list[str]) -> str:
        import httpx
        images_b64 = []
        for path in image_paths:
            with open(path, "rb") as f:
                images_b64.append(base64.b64encode(f.read()).decode())

        payload = {
            "model": provider._model,
            "prompt": prompt,
            "images": images_b64,
            "stream": False,
            "options": {"temperature": 0.1, "num_predict": 1024},
        }
        async with httpx.AsyncClient(timeout=provider._timeout) as client:
            resp = await client.post(f"{provider._base_url}/api/generate", json=payload)
            resp.raise_for_status()
            return resp.json().get("response", "").strip()

    def _parse_score_response(self, response: str) -> dict[str, Any]:
        # Strip markdown code fences if present
        text = re.sub(r"```(?:json)?\s*", "", response).strip().rstrip("```").strip()
        # Find JSON object
        match = re.search(r"\{.*\}", text, re.DOTALL)
        if match:
            try:
                return json.loads(match.group())
            except json.JSONDecodeError:
                pass
        logger.warning("Could not parse AI score response: %s", response[:200])
        return {}

    def _parse_compare_response(self, response: str) -> dict[str, Any]:
        return self._parse_score_response(response)

    def _build_score_result(
        self, asset_id: str, data: dict[str, Any], provider_name: str = ""
    ) -> AIJudgeResult:
        def _get_score(key: str) -> AIJudgeScore:
            val = data.get(key, {})
            if isinstance(val, dict):
                return AIJudgeScore(
                    score=float(val.get("score", 0.5)),
                    reason=str(val.get("reason", "")),
                    not_applicable=bool(val.get("not_applicable", False)),
                )
            return AIJudgeScore(0.5)

        composite_raw = data.get("composite", {})
        if isinstance(composite_raw, dict):
            composite = float(composite_raw.get("score", 0.5))
        else:
            composite = float(composite_raw) if composite_raw else 0.5

        return AIJudgeResult(
            asset_id=asset_id,
            technical_quality=_get_score("technical_quality"),
            aesthetic_quality=_get_score("aesthetic_quality"),
            face_clarity=_get_score("face_clarity"),
            pose_usefulness=_get_score("pose_usefulness"),
            expression_quality=_get_score("expression_quality"),
            background_usefulness=_get_score("background_usefulness"),
            uniqueness=_get_score("uniqueness"),
            training_value=_get_score("training_value"),
            composite=composite,
            strengths=list(data.get("strengths", [])),
            weaknesses=list(data.get("weaknesses", [])),
            recommendation=str(data.get("recommendation", "maybe")),
            confidence=str(data.get("confidence", "low")),
            needs_human_review=bool(data.get("needs_human_review", False)),
            review_reason=str(data.get("review_reason", "")),
            provider_used=provider_name,
            is_fallback=False,
        )

    def _build_compare_result(
        self,
        asset_id_a: str,
        asset_id_b: str,
        data: dict[str, Any],
        provider_name: str = "",
    ) -> AIJudgeComparisonResult:
        winner_letter = str(data.get("winner", "A")).upper()
        if winner_letter == "A":
            winner_asset_id = asset_id_a
        elif winner_letter == "B":
            winner_asset_id = asset_id_b
        else:
            winner_letter = "draw"
            winner_asset_id = asset_id_a  # fallback

        def _get_dim(key: str) -> dict[str, str]:
            val = data.get(key, {})
            if isinstance(val, dict):
                return {"winner": str(val.get("winner", "")), "reason": str(val.get("reason", ""))}
            return {}

        return AIJudgeComparisonResult(
            asset_id_a=asset_id_a,
            asset_id_b=asset_id_b,
            winner=winner_letter,
            winner_asset_id=winner_asset_id,
            confidence=str(data.get("confidence", "low")),
            margin=str(data.get("margin", "negligible")),
            technical_quality=_get_dim("technical_quality"),
            aesthetic_quality=_get_dim("aesthetic_quality"),
            face_clarity=_get_dim("face_clarity"),
            overall_reasoning=str(data.get("overall_reasoning", "")),
            a_strengths=list(data.get("A_strengths", [])),
            b_strengths=list(data.get("B_strengths", [])),
            dataset_contribution=dict(data.get("dataset_contribution", {})),
            provider_used=provider_name,
        )

    def _fallback_score(
        self,
        asset_id: str,
        image_path: str,
        analysis: dict[str, Any],
    ) -> AIJudgeResult:
        """Heuristic scoring from existing pipeline analysis fields."""
        tech = float(analysis.get("technical_quality", 0.5) or 0.5)
        aes = float(analysis.get("aesthetic_score", 0.5) or 0.5)
        face = float(analysis.get("face_quality", 0.5) or 0.5)
        training = float(analysis.get("training_usefulness", 0.5) or 0.5)
        composite = float(analysis.get("composite_score", (tech + aes + training) / 3) or 0.5)

        rec = "keep" if composite >= 0.7 else "maybe" if composite >= 0.4 else "remove"

        return AIJudgeResult(
            asset_id=asset_id,
            technical_quality=AIJudgeScore(score=tech, reason="from pipeline analysis"),
            aesthetic_quality=AIJudgeScore(score=aes, reason="from pipeline analysis"),
            face_clarity=AIJudgeScore(score=face, reason="from pipeline analysis"),
            pose_usefulness=AIJudgeScore(score=0.5, reason="not available in fallback"),
            expression_quality=AIJudgeScore(score=0.5, reason="not available in fallback"),
            background_usefulness=AIJudgeScore(score=0.5, reason="not available in fallback"),
            uniqueness=AIJudgeScore(score=0.5, reason="not available in fallback"),
            training_value=AIJudgeScore(score=training, reason="from pipeline analysis"),
            composite=composite,
            strengths=[],
            weaknesses=[],
            recommendation=rec,
            confidence="low",
            needs_human_review=True,
            review_reason="AI judge unavailable — using heuristic scores",
            provider_used="fallback",
            is_fallback=True,
        )

    def _fallback_compare(
        self,
        asset_id_a: str,
        asset_id_b: str,
        analysis_a: dict[str, Any],
        analysis_b: dict[str, Any],
    ) -> AIJudgeComparisonResult:
        score_a = float(analysis_a.get("composite_score", 0.5) or 0.5)
        score_b = float(analysis_b.get("composite_score", 0.5) or 0.5)

        if abs(score_a - score_b) < 0.05:
            winner = "draw"
            winner_asset_id = asset_id_a
        elif score_a > score_b:
            winner = "A"
            winner_asset_id = asset_id_a
        else:
            winner = "B"
            winner_asset_id = asset_id_b

        return AIJudgeComparisonResult(
            asset_id_a=asset_id_a,
            asset_id_b=asset_id_b,
            winner=winner,
            winner_asset_id=winner_asset_id,
            confidence="low",
            margin="negligible",
            overall_reasoning="AI judge unavailable — based on composite scores",
            provider_used="fallback",
        )


# ── Singleton ─────────────────────────────────────────────────────────────────

_judge: AIJudge | None = None


def get_ai_judge(provider_name: str = "auto") -> AIJudge:
    global _judge
    if _judge is None or _judge._provider_name != provider_name:
        _judge = AIJudge(provider_name)
    return _judge
