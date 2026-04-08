"""Unit tests for the AIJudge service — parsing, building, and fallback logic."""
from __future__ import annotations

import json
from unittest.mock import AsyncMock, patch

import pytest

from services.ai_judge import AIJudge, AIJudgeComparisonResult, AIJudgeResult, AIJudgeScore


# ── Helpers ───────────────────────────────────────────────────────────────────

def _judge() -> AIJudge:
    return AIJudge(provider_name="auto")


# ── _parse_score_response ─────────────────────────────────────────────────────

class TestParseScoreResponse:
    def test_valid_json(self):
        raw = json.dumps({"composite": {"score": 0.8}, "confidence": "high"})
        result = _judge()._parse_score_response(raw)
        assert result["confidence"] == "high"
        assert result["composite"]["score"] == 0.8

    def test_json_in_markdown_code_fence(self):
        raw = '```json\n{"composite": 0.9, "recommendation": "keep"}\n```'
        result = _judge()._parse_score_response(raw)
        assert result["composite"] == 0.9
        assert result["recommendation"] == "keep"

    def test_json_in_plain_code_fence(self):
        raw = '```\n{"technical_quality": {"score": 0.7}}\n```'
        result = _judge()._parse_score_response(raw)
        assert result["technical_quality"]["score"] == 0.7

    def test_invalid_json_returns_empty(self):
        assert _judge()._parse_score_response("not json at all") == {}

    def test_empty_string_returns_empty(self):
        assert _judge()._parse_score_response("") == {}

    def test_json_embedded_in_text(self):
        raw = 'Here is my analysis:\n{"composite": 0.6}\nHope this helps!'
        result = _judge()._parse_score_response(raw)
        assert result["composite"] == 0.6

    def test_nested_json(self):
        raw = json.dumps({
            "technical_quality": {"score": 0.9, "reason": "sharp"},
            "aesthetic_quality": {"score": 0.7, "reason": "good"},
        })
        result = _judge()._parse_score_response(raw)
        assert result["technical_quality"]["score"] == 0.9
        assert result["aesthetic_quality"]["reason"] == "good"


# ── _parse_compare_response ──────────────────────────────────────────────────

class TestParseCompareResponse:
    def test_delegates_to_parse_score_response(self):
        raw = json.dumps({"winner": "A", "confidence": "high"})
        result = _judge()._parse_compare_response(raw)
        assert result["winner"] == "A"

    def test_code_fence_compare(self):
        raw = '```json\n{"winner": "B", "margin": "clear"}\n```'
        result = _judge()._parse_compare_response(raw)
        assert result["winner"] == "B"
        assert result["margin"] == "clear"


# ── _build_score_result ──────────────────────────────────────────────────────

class TestBuildScoreResult:
    def test_full_data(self):
        data = {
            "technical_quality": {"score": 0.9, "reason": "sharp"},
            "aesthetic_quality": {"score": 0.8, "reason": "nice colors"},
            "face_clarity": {"score": 0.7, "reason": "clear", "not_applicable": False},
            "pose_usefulness": {"score": 0.6, "reason": "good pose"},
            "expression_quality": {"score": 0.5, "reason": "neutral"},
            "background_usefulness": {"score": 0.4, "reason": "busy"},
            "uniqueness": {"score": 0.3, "reason": "common"},
            "training_value": {"score": 0.85, "reason": "useful"},
            "composite": {"score": 0.72},
            "strengths": ["sharp", "well-lit"],
            "weaknesses": ["busy bg"],
            "recommendation": "keep",
            "confidence": "high",
            "needs_human_review": False,
            "review_reason": "",
        }
        r = _judge()._build_score_result("asset1", data, provider_name="gemini")
        assert r.asset_id == "asset1"
        assert r.technical_quality.score == 0.9
        assert r.aesthetic_quality.reason == "nice colors"
        assert r.face_clarity.not_applicable is False
        assert r.composite == 0.72
        assert r.strengths == ["sharp", "well-lit"]
        assert r.recommendation == "keep"
        assert r.confidence == "high"
        assert r.provider_used == "gemini"
        assert r.is_fallback is False

    def test_empty_data_defaults(self):
        r = _judge()._build_score_result("a1", {}, provider_name="test")
        assert r.asset_id == "a1"
        assert r.technical_quality.score == 0.5
        assert r.composite == 0.5
        assert r.recommendation == "maybe"
        assert r.confidence == "low"
        assert r.provider_used == "test"

    def test_composite_as_float(self):
        r = _judge()._build_score_result("a2", {"composite": 0.88}, provider_name="")
        assert r.composite == 0.88

    def test_composite_as_dict(self):
        r = _judge()._build_score_result("a3", {"composite": {"score": 0.65}}, provider_name="")
        assert r.composite == 0.65

    def test_missing_dimension_defaults(self):
        data = {"technical_quality": {"score": 0.9, "reason": "great"}}
        r = _judge()._build_score_result("a4", data, provider_name="")
        assert r.technical_quality.score == 0.9
        assert r.uniqueness.score == 0.5

    def test_not_applicable_flag(self):
        data = {"face_clarity": {"score": 0.0, "reason": "no face", "not_applicable": True}}
        r = _judge()._build_score_result("a5", data, provider_name="")
        assert r.face_clarity.not_applicable is True
        assert r.face_clarity.score == 0.0


# ── _build_compare_result ────────────────────────────────────────────────────

class TestBuildCompareResult:
    def test_winner_a(self):
        data = {"winner": "A", "confidence": "high", "margin": "clear"}
        r = _judge()._build_compare_result("id_a", "id_b", data, provider_name="gemini")
        assert r.winner == "A"
        assert r.winner_asset_id == "id_a"
        assert r.confidence == "high"
        assert r.margin == "clear"
        assert r.provider_used == "gemini"

    def test_winner_b(self):
        data = {"winner": "B", "confidence": "medium", "margin": "slight"}
        r = _judge()._build_compare_result("id_a", "id_b", data, provider_name="")
        assert r.winner == "B"
        assert r.winner_asset_id == "id_b"

    def test_winner_draw(self):
        data = {"winner": "draw"}
        r = _judge()._build_compare_result("id_a", "id_b", data, provider_name="")
        assert r.winner == "draw"
        assert r.winner_asset_id == "id_a"  # fallback for draw

    def test_unknown_winner_becomes_draw(self):
        data = {"winner": "tie"}
        r = _judge()._build_compare_result("id_a", "id_b", data, provider_name="")
        assert r.winner == "draw"
        assert r.winner_asset_id == "id_a"

    def test_dimension_extraction(self):
        data = {
            "winner": "A",
            "technical_quality": {"winner": "A", "reason": "sharper"},
            "aesthetic_quality": {"winner": "B", "reason": "better colors"},
            "face_clarity": {"winner": "A", "reason": "clearer"},
            "overall_reasoning": "Image A is better overall",
            "A_strengths": ["sharp"],
            "B_strengths": ["colorful"],
            "dataset_contribution": {"A": "high", "B": "medium"},
            "confidence": "high",
            "margin": "clear",
        }
        r = _judge()._build_compare_result("a1", "b1", data, provider_name="ollama")
        assert r.technical_quality == {"winner": "A", "reason": "sharper"}
        assert r.aesthetic_quality == {"winner": "B", "reason": "better colors"}
        assert r.overall_reasoning == "Image A is better overall"
        assert r.a_strengths == ["sharp"]
        assert r.b_strengths == ["colorful"]
        assert r.dataset_contribution == {"A": "high", "B": "medium"}

    def test_empty_data_defaults(self):
        r = _judge()._build_compare_result("a1", "b1", {}, provider_name="")
        assert r.winner == "A"  # default from data.get("winner", "A")
        assert r.winner_asset_id == "a1"
        assert r.confidence == "low"
        assert r.margin == "negligible"

    def test_lowercase_winner_normalized(self):
        data = {"winner": "b"}
        r = _judge()._build_compare_result("id_a", "id_b", data, provider_name="")
        assert r.winner == "B"
        assert r.winner_asset_id == "id_b"


# ── _fallback_score ──────────────────────────────────────────────────────────

class TestFallbackScore:
    def test_with_analysis_data(self):
        analysis = {
            "technical_quality": 0.8,
            "aesthetic_score": 0.7,
            "face_quality": 0.6,
            "training_usefulness": 0.9,
            "composite_score": 0.75,
        }
        r = _judge()._fallback_score("a1", "/fake/path.jpg", analysis)
        assert r.asset_id == "a1"
        assert r.technical_quality.score == 0.8
        assert r.aesthetic_quality.score == 0.7
        assert r.face_clarity.score == 0.6
        assert r.training_value.score == 0.9
        assert r.composite == 0.75
        assert r.is_fallback is True
        assert r.confidence == "low"
        assert r.provider_used == "fallback"
        assert r.needs_human_review is True

    def test_empty_analysis_defaults(self):
        r = _judge()._fallback_score("a2", "/fake/path.jpg", {})
        assert r.technical_quality.score == 0.5
        assert r.aesthetic_quality.score == 0.5
        assert r.composite == 0.5
        assert r.is_fallback is True

    def test_recommendation_keep(self):
        analysis = {"composite_score": 0.75}
        r = _judge()._fallback_score("a3", "/fake/path.jpg", analysis)
        assert r.recommendation == "keep"

    def test_recommendation_keep_boundary(self):
        analysis = {"composite_score": 0.7}
        r = _judge()._fallback_score("a4", "/fake/path.jpg", analysis)
        assert r.recommendation == "keep"

    def test_recommendation_maybe(self):
        analysis = {"composite_score": 0.5}
        r = _judge()._fallback_score("a5", "/fake/path.jpg", analysis)
        assert r.recommendation == "maybe"

    def test_recommendation_maybe_boundary(self):
        analysis = {"composite_score": 0.4}
        r = _judge()._fallback_score("a6", "/fake/path.jpg", analysis)
        assert r.recommendation == "maybe"

    def test_recommendation_remove(self):
        analysis = {"composite_score": 0.2}
        r = _judge()._fallback_score("a7", "/fake/path.jpg", analysis)
        assert r.recommendation == "remove"

    def test_recommendation_remove_boundary(self):
        analysis = {"composite_score": 0.39}
        r = _judge()._fallback_score("a8", "/fake/path.jpg", analysis)
        assert r.recommendation == "remove"

    def test_computed_composite_when_not_provided(self):
        analysis = {
            "technical_quality": 0.9,
            "aesthetic_score": 0.6,
            "training_usefulness": 0.3,
        }
        r = _judge()._fallback_score("a9", "/fake/path.jpg", analysis)
        assert r.composite == pytest.approx((0.9 + 0.6 + 0.3) / 3)

    def test_fallback_dimensions_default(self):
        r = _judge()._fallback_score("a10", "/fake/path.jpg", {})
        assert r.pose_usefulness.score == 0.5
        assert r.pose_usefulness.reason == "not available in fallback"
        assert r.expression_quality.score == 0.5
        assert r.background_usefulness.score == 0.5
        assert r.uniqueness.score == 0.5


# ── _fallback_compare ────────────────────────────────────────────────────────

class TestFallbackCompare:
    def test_a_wins(self):
        a = {"composite_score": 0.8}
        b = {"composite_score": 0.3}
        r = _judge()._fallback_compare("id_a", "id_b", a, b)
        assert r.winner == "A"
        assert r.winner_asset_id == "id_a"
        assert r.confidence == "low"
        assert r.provider_used == "fallback"

    def test_b_wins(self):
        a = {"composite_score": 0.3}
        b = {"composite_score": 0.8}
        r = _judge()._fallback_compare("id_a", "id_b", a, b)
        assert r.winner == "B"
        assert r.winner_asset_id == "id_b"

    def test_draw_within_threshold(self):
        a = {"composite_score": 0.50}
        b = {"composite_score": 0.52}
        r = _judge()._fallback_compare("id_a", "id_b", a, b)
        assert r.winner == "draw"
        assert r.winner_asset_id == "id_a"

    def test_draw_exact_equal(self):
        a = {"composite_score": 0.5}
        b = {"composite_score": 0.5}
        r = _judge()._fallback_compare("id_a", "id_b", a, b)
        assert r.winner == "draw"

    def test_not_draw_at_boundary(self):
        a = {"composite_score": 0.55}
        b = {"composite_score": 0.5}
        r = _judge()._fallback_compare("id_a", "id_b", a, b)
        assert r.winner == "A"

    def test_empty_analysis_defaults_to_draw(self):
        r = _judge()._fallback_compare("id_a", "id_b", {}, {})
        assert r.winner == "draw"
        assert r.margin == "negligible"

    def test_overall_reasoning_set(self):
        r = _judge()._fallback_compare("id_a", "id_b", {}, {})
        assert "unavailable" in r.overall_reasoning.lower()


# ── score_image / compare_images fallback paths ─────────────────────────────

class TestScoreImageFallback:
    @pytest.mark.asyncio
    async def test_falls_back_when_no_provider(self):
        judge = _judge()
        with patch.object(judge, "_get_provider", new_callable=AsyncMock, return_value=(None, {})):
            r = await judge.score_image("/fake/image.jpg", "asset1", existing_analysis={"composite_score": 0.8})
        assert r.is_fallback is True
        assert r.provider_used == "fallback"
        assert r.composite == 0.8

    @pytest.mark.asyncio
    async def test_falls_back_with_empty_analysis(self):
        judge = _judge()
        with patch.object(judge, "_get_provider", new_callable=AsyncMock, return_value=(None, {})):
            r = await judge.score_image("/fake/image.jpg", "asset2")
        assert r.is_fallback is True
        assert r.composite == 0.5


class TestCompareImagesFallback:
    @pytest.mark.asyncio
    async def test_falls_back_when_no_provider(self):
        judge = _judge()
        with patch.object(judge, "_get_provider", new_callable=AsyncMock, return_value=(None, {})):
            r = await judge.compare_images("/fake/a.jpg", "id_a", "/fake/b.jpg", "id_b")
        assert r.winner == "draw"
        assert r.provider_used == "fallback"
        assert r.confidence == "low"
