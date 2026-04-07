"""
Tests for face analysis helpers:
  - compute_face_sharpness  (Laplacian variance, in analysis.py)
  - compute_cluster_consistency  (cosine-similarity centroid score, in face_clustering.py)
"""
from __future__ import annotations

import io
import math
import struct

import numpy as np
import pytest
from PIL import Image

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_png_bytes(width: int, height: int, mode: str = "L") -> bytes:
    """Return raw PNG bytes for a synthetic image."""
    buf = io.BytesIO()
    Image.new(mode, (width, height), color=128).save(buf, format="PNG")
    buf.seek(0)
    return buf.read()


def _make_sharp_image(tmp_path) -> tuple[str, dict]:
    """Create a checkerboard PNG (high-frequency → high Laplacian variance)."""
    arr = np.tile(
        np.array([[0, 255], [255, 0]], dtype=np.uint8), (64, 64)
    )  # 128×128
    img = Image.fromarray(arr, mode="L")
    p = tmp_path / "sharp.png"
    img.save(p)
    # Face bbox covers the whole image
    return str(p), {"x1": 0.0, "y1": 0.0, "x2": 128.0, "y2": 128.0}


def _make_blurry_image(tmp_path) -> tuple[str, dict]:
    """Create a uniform-grey PNG (zero variance → Laplacian ~ 0)."""
    img = Image.new("L", (128, 128), color=128)
    p = tmp_path / "blurry.png"
    img.save(p)
    return str(p), {"x1": 0.0, "y1": 0.0, "x2": 128.0, "y2": 128.0}


# ---------------------------------------------------------------------------
# Tests for compute_face_sharpness
# ---------------------------------------------------------------------------


class TestComputeFaceSharpness:
    def test_sharp_image_returns_high_score(self, tmp_path):
        from services.analysis import compute_face_sharpness

        path, bbox = _make_sharp_image(tmp_path)
        score = compute_face_sharpness(path, bbox)
        assert score is not None
        assert score >= 0.5, f"Expected high sharpness, got {score}"

    def test_blurry_image_returns_low_score(self, tmp_path):
        from services.analysis import compute_face_sharpness

        path, bbox = _make_blurry_image(tmp_path)
        score = compute_face_sharpness(path, bbox)
        assert score is not None
        assert score < 0.05, f"Expected near-zero sharpness for uniform image, got {score}"

    def test_score_clamped_to_0_1(self, tmp_path):
        from services.analysis import compute_face_sharpness

        path, bbox = _make_sharp_image(tmp_path)
        score = compute_face_sharpness(path, bbox)
        assert score is not None
        assert 0.0 <= score <= 1.0

    def test_invalid_path_returns_none(self):
        from services.analysis import compute_face_sharpness

        score = compute_face_sharpness("/nonexistent/path.png", {"x1": 0, "y1": 0, "x2": 64, "y2": 64})
        assert score is None

    def test_empty_bbox_returns_none(self, tmp_path):
        from services.analysis import compute_face_sharpness

        path, _ = _make_blurry_image(tmp_path)
        # Degenerate bbox (zero area)
        score = compute_face_sharpness(path, {"x1": 10.0, "y1": 10.0, "x2": 10.0, "y2": 10.0})
        assert score is None

    def test_sharp_image_scores_higher_than_blurry(self, tmp_path):
        from services.analysis import compute_face_sharpness

        sharp_path, sharp_bbox = _make_sharp_image(tmp_path)
        blurry_path, blurry_bbox = _make_blurry_image(tmp_path)

        sharp_score = compute_face_sharpness(sharp_path, sharp_bbox)
        blurry_score = compute_face_sharpness(blurry_path, blurry_bbox)

        assert sharp_score is not None
        assert blurry_score is not None
        assert sharp_score > blurry_score


# ---------------------------------------------------------------------------
# Tests for compute_cluster_consistency
# ---------------------------------------------------------------------------


def _unit(v: list[float]) -> np.ndarray:
    a = np.array(v, dtype=np.float32)
    return (a / np.linalg.norm(a)).reshape(1, -1)


class TestComputeClusterConsistency:
    def test_single_vector_returns_1(self):
        from services.face_clustering import compute_cluster_consistency

        v = _unit([1.0, 0.0, 0.0])
        score = compute_cluster_consistency(v)
        assert math.isclose(score, 1.0, abs_tol=1e-6)

    def test_identical_vectors_return_1(self):
        from services.face_clustering import compute_cluster_consistency

        v = _unit([1.0, 0.0, 0.0])
        vecs = np.repeat(v, 5, axis=0)
        score = compute_cluster_consistency(vecs)
        assert math.isclose(score, 1.0, abs_tol=1e-5)

    def test_orthogonal_vectors_return_low_score(self):
        from services.face_clustering import compute_cluster_consistency

        # Two perfectly orthogonal unit vectors — cluster is maximally spread.
        vecs = np.array([[1.0, 0.0], [0.0, 1.0]], dtype=np.float32)
        score = compute_cluster_consistency(vecs)
        # Centroid = [0.707, 0.707] (normalised); similarity of each to that ≈ 0.707
        assert score < 0.8

    def test_similar_vectors_return_high_score(self):
        from services.face_clustering import compute_cluster_consistency

        rng = np.random.default_rng(42)
        base = np.array([1.0, 0.0, 0.0, 0.0], dtype=np.float32)
        # Small perturbations around base direction
        vecs = base + rng.normal(0, 0.05, (20, 4)).astype(np.float32)
        norms = np.linalg.norm(vecs, axis=1, keepdims=True)
        vecs /= norms
        score = compute_cluster_consistency(vecs)
        assert score >= 0.9, f"Expected high consistency for tightly grouped cluster, got {score}"

    def test_empty_input_returns_zero(self):
        from services.face_clustering import compute_cluster_consistency

        score = compute_cluster_consistency(np.empty((0, 0), dtype=np.float32))
        assert score == 0.0

    def test_score_in_0_1_range(self):
        from services.face_clustering import compute_cluster_consistency

        rng = np.random.default_rng(7)
        vecs = rng.standard_normal((50, 128)).astype(np.float32)
        norms = np.linalg.norm(vecs, axis=1, keepdims=True)
        vecs /= norms
        score = compute_cluster_consistency(vecs)
        assert 0.0 <= score <= 1.0
