"""Preferences API tests — GET/PATCH /api/preferences."""
from __future__ import annotations

import pytest


@pytest.mark.asyncio
async def test_get_preferences_returns_defaults(client):
    """GET /api/preferences returns the singleton row with default values."""
    r = await client.get("/api/preferences")
    assert r.status_code == 200
    body = r.json()
    assert body["theme"] == "dark"
    assert body["gallery_zoom"] == 1
    assert body["sidebar_collapsed"] is False
    assert body["default_sort_by"] == "composite_score"
    assert body["default_sort_dir"] == "desc"
    assert body["auto_analyze_on_import"] is True
    assert body["auto_caption_on_import"] is False
    assert body["default_caption_provider"] is None
    assert body["default_caption_style"] == "natural"
    assert body["min_quality_for_export"] == 0.5
    assert body["auto_reject_below"] is None
    assert body["duplicate_action"] == "flag"
    assert body["extra"] is None


@pytest.mark.asyncio
async def test_update_single_preference(client):
    """PATCH /api/preferences with one field updates only that field."""
    r = await client.patch("/api/preferences", json={"theme": "light"})
    assert r.status_code == 200
    body = r.json()
    assert body["theme"] == "light"
    # Other fields unchanged
    assert body["gallery_zoom"] == 1
    assert body["sidebar_collapsed"] is False
    assert body["auto_analyze_on_import"] is True
    assert body["duplicate_action"] == "flag"


@pytest.mark.asyncio
async def test_update_multiple_preferences(client):
    """PATCH /api/preferences with multiple fields updates all of them."""
    r = await client.patch("/api/preferences", json={
        "theme": "dark",
        "gallery_zoom": 2,
    })
    assert r.status_code == 200
    body = r.json()
    assert body["theme"] == "dark"
    assert body["gallery_zoom"] == 2


@pytest.mark.asyncio
async def test_partial_update_preserves_unset_fields(client):
    """PATCH with auto_reject_below leaves other fields at their current values."""
    # First set a known state
    await client.patch("/api/preferences", json={
        "theme": "dark",
        "gallery_zoom": 1,
    })

    # Now update only auto_reject_below
    r = await client.patch("/api/preferences", json={"auto_reject_below": 0.3})
    assert r.status_code == 200
    body = r.json()
    assert body["auto_reject_below"] == 0.3
    assert body["theme"] == "dark"
    assert body["gallery_zoom"] == 1
    assert body["auto_analyze_on_import"] is True
    assert body["default_sort_by"] == "composite_score"


@pytest.mark.asyncio
async def test_update_extra_json_field(client):
    """PATCH /api/preferences can set the extra JSON field to a dict."""
    payload = {"extra": {"custom_key": "custom_value", "nested": {"a": 1}}}
    r = await client.patch("/api/preferences", json=payload)
    assert r.status_code == 200
    body = r.json()
    assert body["extra"] == {"custom_key": "custom_value", "nested": {"a": 1}}

    # Confirm via GET
    r2 = await client.get("/api/preferences")
    assert r2.status_code == 200
    assert r2.json()["extra"] == payload["extra"]
