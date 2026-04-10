"""Tests for faces and identity cluster API endpoints."""
from __future__ import annotations

import pytest
from models.asset import Asset
from models.face import IdentityCluster
from models.project import Project


async def _create_project(db) -> Project:
    project = Project(name="faces-test", description="")
    db.add(project)
    await db.flush()
    return project


async def _create_cluster(db, project_id, label="Person A", asset_count=0, **kwargs) -> IdentityCluster:
    cluster = IdentityCluster(project_id=project_id, label=label, asset_count=asset_count, **kwargs)
    db.add(cluster)
    await db.flush()
    return cluster


async def _create_asset(db, project_id, filename="face.png", identity_cluster_id=None, **kwargs) -> Asset:
    asset = Asset(
        project_id=project_id,
        filename=filename,
        filepath=f"/tmp/fake/{filename}",
        mime_type="image/png",
        width=512, height=512,
        identity_cluster_id=identity_cluster_id,
        **kwargs,
    )
    db.add(asset)
    await db.flush()
    return asset


@pytest.mark.asyncio
async def test_list_identities_empty(client, db):
    project = await _create_project(db)
    await db.commit()
    r = await client.get(f"/api/projects/{project.id}/identities")
    assert r.status_code == 200
    assert r.json() == []


@pytest.mark.asyncio
async def test_list_identities_returns_clusters_ordered_by_count(client, db):
    project = await _create_project(db)
    c1 = await _create_cluster(db, project.id, label="Person A", asset_count=3)
    c2 = await _create_cluster(db, project.id, label="Person B", asset_count=10)
    await db.commit()
    r = await client.get(f"/api/projects/{project.id}/identities")
    assert r.status_code == 200
    body = r.json()
    assert len(body) == 2
    assert body[0]["label"] == "Person B"
    assert body[0]["asset_count"] == 10
    assert body[1]["label"] == "Person A"


@pytest.mark.asyncio
async def test_update_identity_label(client, db):
    project = await _create_project(db)
    cluster = await _create_cluster(db, project.id, label="Unknown")
    await db.commit()
    r = await client.patch(f"/api/identities/{cluster.id}?label=Jane+Doe")
    assert r.status_code == 200
    body = r.json()
    assert body["ok"] is True
    assert body["label"] == "Jane Doe"


@pytest.mark.asyncio
async def test_update_identity_is_subject(client, db):
    project = await _create_project(db)
    cluster = await _create_cluster(db, project.id, label="Subject", is_subject=False)
    await db.commit()
    r = await client.patch(f"/api/identities/{cluster.id}?is_subject=true")
    assert r.status_code == 200
    assert r.json()["ok"] is True


@pytest.mark.asyncio
async def test_update_identity_not_found(client):
    r = await client.patch("/api/identities/nonexistent?label=Test")
    assert r.status_code == 404


@pytest.mark.asyncio
async def test_list_face_clusters_with_assets(client, db):
    project = await _create_project(db)
    cluster = await _create_cluster(db, project.id, label="Cluster1", asset_count=2, thumbnail_asset_id="thumb1")
    asset1 = await _create_asset(db, project.id, "a1.png", identity_cluster_id=cluster.id)
    asset2 = await _create_asset(db, project.id, "a2.png", identity_cluster_id=cluster.id)
    await db.commit()
    r = await client.get(f"/api/faces/clusters?project_id={project.id}")
    assert r.status_code == 200
    body = r.json()
    assert len(body) == 1
    assert body[0]["label"] == "Cluster1"
    assert body[0]["face_count"] == 2
    assert len(body[0]["asset_ids"]) == 2
    assert body[0]["thumbnail_url"] == "/api/assets/thumb1/thumbnail"


@pytest.mark.asyncio
async def test_list_cluster_assets(client, db):
    project = await _create_project(db)
    cluster = await _create_cluster(db, project.id, label="ClusterX")
    asset = await _create_asset(db, project.id, "face1.png", identity_cluster_id=cluster.id, composite_score=0.85)
    await db.commit()
    r = await client.get(f"/api/faces/clusters/{cluster.id}/assets")
    assert r.status_code == 200
    body = r.json()
    assert len(body) == 1
    assert body[0]["filename"] == "face1.png"
    assert body[0]["composite_score"] == 0.85


@pytest.mark.asyncio
async def test_list_cluster_assets_empty(client, db):
    project = await _create_project(db)
    cluster = await _create_cluster(db, project.id, label="Empty")
    await db.commit()
    r = await client.get(f"/api/faces/clusters/{cluster.id}/assets")
    assert r.status_code == 200
    assert r.json() == []


@pytest.mark.asyncio
async def test_rename_cluster(client, db):
    project = await _create_project(db)
    cluster = await _create_cluster(db, project.id, label="Old Name")
    await db.commit()
    r = await client.post(f"/api/faces/clusters/{cluster.id}/rename", json={"label": "New Name"})
    assert r.status_code == 200
    assert r.json()["label"] == "New Name"


@pytest.mark.asyncio
async def test_rename_cluster_not_found(client):
    r = await client.post("/api/faces/clusters/nonexistent/rename", json={"label": "X"})
    assert r.status_code == 404


@pytest.mark.asyncio
async def test_merge_clusters(client, db):
    project = await _create_project(db)
    source = await _create_cluster(db, project.id, label="Source", asset_count=2)
    target = await _create_cluster(db, project.id, label="Target", asset_count=1)
    a1 = await _create_asset(db, project.id, "s1.png", identity_cluster_id=source.id)
    a2 = await _create_asset(db, project.id, "s2.png", identity_cluster_id=source.id)
    a3 = await _create_asset(db, project.id, "t1.png", identity_cluster_id=target.id)
    await db.commit()
    r = await client.post("/api/faces/clusters/merge", json={
        "source_id": source.id,
        "target_id": target.id,
    })
    assert r.status_code == 200
    body = r.json()
    assert body["merged"] is True
    assert body["target_id"] == target.id
    assert body["new_face_count"] == 3
