"""Tests for services/asset_quality.py."""
from __future__ import annotations

from types import SimpleNamespace
from services.asset_quality import asset_quality_tuple, pick_best_asset


def _make_asset(**kwargs) -> SimpleNamespace:
    defaults = dict(
        id="a1", project_id="p1", filename="x.png", filepath="/fake/x.png",
        composite_score=None, training_usefulness=None, technical_quality=None,
        face_quality=None, aesthetic_score=None, uniqueness_score=None,
        redundancy_score=None, width=None, height=None,
    )
    defaults.update(kwargs)
    return SimpleNamespace(**defaults)


def test_quality_tuple_all_none():
    a = _make_asset()
    t = asset_quality_tuple(a)
    assert len(t) == 8
    assert all(v == 0.0 for v in t)


def test_quality_tuple_with_scores():
    a = _make_asset(
        composite_score=0.8, training_usefulness=0.7, technical_quality=0.9,
        face_quality=0.6, aesthetic_score=0.5, uniqueness_score=0.4,
        redundancy_score=0.3, width=1024, height=768,
    )
    t = asset_quality_tuple(a)
    assert t[0] == 0.8  # composite
    assert t[6] == -0.3  # negative redundancy
    assert t[7] == 1024 * 768  # pixel count


def test_quality_tuple_negative_redundancy():
    a = _make_asset(redundancy_score=0.9)
    t = asset_quality_tuple(a)
    assert t[6] == -0.9


def test_pick_best_asset_single():
    a = _make_asset(id="a1", composite_score=0.5)
    result = pick_best_asset(["a1"], {"a1": a})
    assert result == "a1"


def test_pick_best_asset_prefers_higher_composite():
    a1 = _make_asset(id="a1", composite_score=0.3)
    a2 = _make_asset(id="a2", composite_score=0.9)
    result = pick_best_asset(["a1", "a2"], {"a1": a1, "a2": a2})
    assert result == "a2"


def test_pick_best_asset_tie_breaks_by_id():
    a1 = _make_asset(id="aaa", composite_score=0.5)
    a2 = _make_asset(id="zzz", composite_score=0.5)
    result = pick_best_asset(["aaa", "zzz"], {"aaa": a1, "zzz": a2})
    assert result == "zzz"  # higher id wins


def test_pick_best_asset_uses_secondary_criteria():
    a1 = _make_asset(id="a1", composite_score=0.5, training_usefulness=0.9)
    a2 = _make_asset(id="a2", composite_score=0.5, training_usefulness=0.1)
    result = pick_best_asset(["a1", "a2"], {"a1": a1, "a2": a2})
    assert result == "a1"  # same composite, higher training_usefulness
