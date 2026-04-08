"""Faces and identity cluster API tests."""
from __future__ import annotations

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from models.asset import Asset
from models.face import IdentityCluster
from models.project import Project


async def _setup_face_data(db: AsyncSession):
    """Seed a project with two identity clusters and three assets."""
    project = Project(name="face-test", description="")
    db.add(project)
    await db.flush()

    cluster1 = IdentityCluster(
        project_id=project.id, label="Person 1", asset_count=2,
    )
    cluster2 = IdentityCluster(
        project_id=project.id, label="Person 2", asset_count=1,
    )
    db.add_all([cluster1, cluster2])
    await db.flush()

    asset1 = Asset(
        project_id=project.id, filename="a.png", filepath="/data/a.png",
        identity_cluster_id=cluster1.id, composite_score=0.8,
    )
    asset2 = Asset(
        project_id=project.id, filename="b.png", filepath="/data/b.png",
        identity_cluster_id=cluster1.id, composite_score=0.6,
    )
    asset3 = Asset(
        project_id=project.id, filename="c.png", filepath="/data/c.png",
        identity_cluster_id=cluster2.id, composite_score=0.9,
    )
    db.add_all([asset1, asset2, asset3])
    await db.flush()
    return project, [cluster1, cluster2], [asset1, asset2, asset3]


# ── List identities ──────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_list_identities_empty(client):
    """A project with no clusters returns an empty list."""
    # Create an empty project via API
    r = await client.post("/api/projects", json={"name": "empty-faces", "description": ""})
    pid = r.json()["id"]

    r = await client.get(f"/api/projects/{pid}/identities")
    assert r.status_code == 200
    assert r.json() == []


@pytest.mark.asyncio
async def test_list_identities_with_data(client, db):
    """Returns identity cluster info for a project with data."""
    project, clusters, _ = await _setup_face_data(db)
    await db.commit()

    r = await client.get(f"/api/projects/{project.id}/identities")
    assert r.status_code == 200
    body = r.json()
    assert len(body) == 2
    labels = {c["label"] for c in body}
    assert "Person 1" in labels
    assert "Person 2" in labels
    # Sorted by asset_count desc — Person 1 (2) comes first
    assert body[0]["asset_count"] >= body[1]["asset_count"]


# ── Update identity ──────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_update_identity_label(client, db):
    """PATCH /api/identities/{id}?label=... updates the label."""
    project, clusters, _ = await _setup_face_data(db)
    await db.commit()
    cluster_id = clusters[0].id

    r = await client.patch(f"/api/identities/{cluster_id}", params={"label": "Alice"})
    assert r.status_code == 200
    body = r.json()
    assert body["ok"] is True
    assert body["label"] == "Alice"


@pytest.mark.asyncio
async def test_update_identity_not_found(client):
    """PATCH for a nonexistent cluster returns 404."""
    r = await client.patch(
        "/api/identities/00000000-0000-0000-0000-000000000000",
        params={"label": "Ghost"},
    )
    assert r.status_code == 404


# ── Face clusters ────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_list_face_clusters_with_asset_ids(client, db):
    """GET /api/faces/clusters?project_id=... includes asset_ids list."""
    project, clusters, assets = await _setup_face_data(db)
    await db.commit()

    r = await client.get("/api/faces/clusters", params={"project_id": project.id})
    assert r.status_code == 200
    body = r.json()
    assert len(body) == 2

    # Find the cluster with label "Person 1"
    c1 = next(c for c in body if c["label"] == "Person 1")
    assert len(c1["asset_ids"]) == 2
    assert c1["face_count"] == 2


@pytest.mark.asyncio
async def test_list_cluster_assets(client, db):
    """GET /api/faces/clusters/{id}/assets returns assets in that cluster."""
    project, clusters, assets = await _setup_face_data(db)
    await db.commit()
    cluster_id = clusters[0].id

    r = await client.get(f"/api/faces/clusters/{cluster_id}/assets")
    assert r.status_code == 200
    body = r.json()
    assert len(body) == 2
    filenames = {a["filename"] for a in body}
    assert filenames == {"a.png", "b.png"}


# ── Rename ───────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_rename_cluster(client, db):
    """POST /api/faces/clusters/{id}/rename changes the label."""
    project, clusters, _ = await _setup_face_data(db)
    await db.commit()
    cluster_id = clusters[0].id

    r = await client.post(
        f"/api/faces/clusters/{cluster_id}/rename",
        json={"label": "Bob"},
    )
    assert r.status_code == 200
    assert r.json()["label"] == "Bob"


@pytest.mark.asyncio
async def test_rename_cluster_not_found(client):
    """POST rename for nonexistent cluster returns 404."""
    r = await client.post(
        "/api/faces/clusters/00000000-0000-0000-0000-000000000000/rename",
        json={"label": "Nobody"},
    )
    assert r.status_code == 404


# ── Merge ────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_merge_clusters(client, db):
    """POST /api/faces/clusters/merge reassigns assets and deletes source."""
    project, clusters, assets = await _setup_face_data(db)
    await db.commit()
    source_id = clusters[1].id
    target_id = clusters[0].id

    r = await client.post("/api/faces/clusters/merge", json={
        "source_id": source_id,
        "target_id": target_id,
    })
    assert r.status_code == 200
    body = r.json()
    assert body["merged"] is True
    assert body["target_id"] == target_id
    # All 3 assets should now belong to target
    assert body["new_face_count"] == 3

    # Source cluster should be deleted — expire cached state first
    db.expire_all()
    source = await db.get(IdentityCluster, source_id)
    assert source is None
