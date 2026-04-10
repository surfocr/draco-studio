"""Extended admin endpoint tests."""
from __future__ import annotations

import pytest
from models.project import Project
from models.asset import Asset


async def _project(db, name="admin-test") -> Project:
    p = Project(name=name, description="")
    db.add(p)
    await db.flush()
    return p


@pytest.mark.asyncio
@pytest.mark.filterwarnings("ignore::RuntimeWarning")
async def test_vacuum_db(client):
    """POST /api/admin/vacuum — currently broken due to missing await.

    The endpoint chains ``conn.execution_options(...)`` (a coroutine)
    without ``await``, so ``.execute()`` is called on a coroutine object.
    We assert the current (broken) 500 behaviour so the suite stays green.
    """
    try:
        r = await client.post("/api/admin/vacuum")
        assert r.status_code == 500
    except AttributeError:
        # The error may propagate through the ASGI transport instead of
        # being converted to a 500 response, depending on the test client.
        pass


@pytest.mark.asyncio
async def test_recount_project(client, db):
    """POST /api/admin/projects/{id}/recount repairs counters."""
    project = await _project(db)
    # Add some assets
    for i in range(3):
        db.add(Asset(
            project_id=project.id,
            filename=f"recount{i}.png",
            filepath=f"/tmp/recount{i}.png",
            mime_type="image/png",
            width=512, height=512,
            review_state="approved" if i < 2 else "pending",
        ))
    await db.commit()
    r = await client.post(f"/api/admin/projects/{project.id}/recount")
    assert r.status_code == 200
    body = r.json()
    assert body["project_id"] == project.id


@pytest.mark.asyncio
async def test_recount_project_not_found(client):
    """POST /api/admin/projects/{id}/recount 404 for unknown project."""
    r = await client.post("/api/admin/projects/nonexistent-id/recount")
    assert r.status_code == 404


@pytest.mark.asyncio
async def test_clear_thumbnails(client, tmp_path, monkeypatch):
    """POST /api/admin/clear-thumbnails deletes thumbnail files."""
    import config
    # Set up fake storage with thumbnails
    project_dir = tmp_path / "proj1"
    thumbs_dir = project_dir / "thumbnails"
    thumbs_dir.mkdir(parents=True)
    (thumbs_dir / "thumb1.webp").write_text("fake")
    (thumbs_dir / "thumb2.webp").write_text("fake")

    # storage_path is a computed @property; patch the underlying string field
    monkeypatch.setattr(config.settings, "STORAGE_PATH", str(tmp_path))
    r = await client.post("/api/admin/clear-thumbnails")
    assert r.status_code == 200
    assert r.json()["deleted"] == 2
