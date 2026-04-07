from __future__ import annotations

from contextlib import asynccontextmanager

import pytest
from httpx import ASGITransport, AsyncClient

from database import get_db
from models.asset import Asset
from models.project import Project
from providers.registry import get_registry
from services.duplicate import find_duplicates


async def _create_project(db, name: str = "duplicates") -> Project:
    project = Project(name=name, description="")
    db.add(project)
    await db.flush()
    return project


async def _create_asset(
    db,
    project_id: str,
    filename: str,
    *,
    sha256_hash: str,
    composite_score: float,
) -> Asset:
    asset = Asset(
        project_id=project_id,
        filename=filename,
        filepath=f"C:/dataset/{filename}",
        mime_type="image/png",
        width=512,
        height=512,
        sha256_hash=sha256_hash,
        composite_score=composite_score,
        technical_quality=composite_score,
    )
    db.add(asset)
    await db.flush()
    return asset


@asynccontextmanager
async def _client_for_db(db):
    from main import app

    async def override_get_db():
        yield db

    app.dependency_overrides[get_db] = override_get_db
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        yield client
    app.dependency_overrides.clear()


@pytest.fixture
def clean_registry():
    registry = get_registry()
    saved_classes = dict(registry._classes)
    saved_instances = dict(registry._instances)
    saved_configs = dict(registry._configs)
    registry._classes.clear()
    registry._instances.clear()
    registry._configs.clear()
    yield
    registry._classes.clear()
    registry._instances.clear()
    registry._configs.clear()
    registry._classes.update(saved_classes)
    registry._instances.update(saved_instances)
    registry._configs.update(saved_configs)


@pytest.mark.asyncio
async def test_duplicates_endpoint_returns_stable_cluster_contract(db, clean_registry):
    project = await _create_project(db)
    lower = await _create_asset(
        db,
        project.id,
        "lower.png",
        sha256_hash="hash-1",
        composite_score=0.65,
    )
    higher = await _create_asset(
        db,
        project.id,
        "higher.png",
        sha256_hash="hash-1",
        composite_score=0.92,
    )

    async with _client_for_db(db) as client:
        response = await client.get(f"/api/projects/{project.id}/duplicates")

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["total_clusters"] == 1
    assert body["total_duplicates"] == 1
    assert len(body["clusters"]) == 1

    cluster = body["clusters"][0]
    assert cluster["cluster_type"] == "exact"
    assert cluster["image_count"] == 2
    assert cluster["best_id"] == higher.id
    assert [image["id"] for image in cluster["images"]] == [higher.id, lower.id]
    assert cluster["images"][0]["keep"] is True
    assert cluster["images"][1]["keep"] is False


@pytest.mark.asyncio
async def test_find_duplicates_prefers_highest_quality_representative_for_exact_clusters(
    db,
    clean_registry,
):
    project = await _create_project(db, "exact-quality")
    lower = await _create_asset(
        db,
        project.id,
        "lower.png",
        sha256_hash="shared-hash",
        composite_score=0.40,
    )
    higher = await _create_asset(
        db,
        project.id,
        "higher.png",
        sha256_hash="shared-hash",
        composite_score=0.93,
    )
    higher.training_usefulness = 0.95
    await db.commit()

    clusters = await find_duplicates(project.id, db, stages=["exact"])

    assert len(clusters) == 1
    assert clusters[0].cluster_type == "exact"
    assert set(clusters[0].asset_ids) == {lower.id, higher.id}
    assert clusters[0].representative_id == higher.id


@pytest.mark.asyncio
async def test_duplicate_scan_endpoint_queues_background_job(client):
    create = await client.post("/api/projects", json={"name": "Duplicate Scan"})
    project_id = create.json()["id"]

    from unittest.mock import AsyncMock, patch

    with patch("api.duplicates.queue_duplicate_scan", new_callable=AsyncMock) as mock_scan:
        mock_scan.return_value = "duplicate-job-1"
        response = await client.post(f"/api/projects/{project_id}/duplicates/scan")

    assert response.status_code == 202, response.text
    assert response.json() == {"job_id": "duplicate-job-1"}


class _FakeCollectionList:
    def __init__(self, names: list[str]):
        self.collections = [type("Collection", (), {"name": name}) for name in names]


class _FakePoint:
    def __init__(self, asset_id: str, vector: list[float], face_index: int = 0):
        self.payload = {"asset_id": asset_id, "project_id": "ignored", "face_index": face_index}
        self.vector = vector


class _FakeQdrant:
    def __init__(self, collection_name: str, points: list[_FakePoint]):
        self._collection_name = collection_name
        self._points = points

    def get_collections(self):
        return _FakeCollectionList([self._collection_name])

    def scroll(self, **kwargs):
        return self._points, None


class _FakeEmbedProvider:
    def __init__(self, qdrant):
        self._qdrant = qdrant


@pytest.mark.asyncio
async def test_find_duplicates_detects_face_similarity_clusters(db, clean_registry):
    from config import settings

    project = await _create_project(db, "face-duplicates")
    asset_a = await _create_asset(
        db,
        project.id,
        "face-a.png",
        sha256_hash="face-a",
        composite_score=0.60,
    )
    asset_b = await _create_asset(
        db,
        project.id,
        "face-b.png",
        sha256_hash="face-b",
        composite_score=0.95,
    )
    asset_a.face_embedding_id = asset_a.id
    asset_b.face_embedding_id = asset_b.id
    await db.commit()

    registry = get_registry()
    fake_provider = _FakeEmbedProvider(
        _FakeQdrant(
            settings.QDRANT_FACE_COLLECTION,
            [
                _FakePoint(asset_a.id, [1.0, 0.0, 0.0]),
                _FakePoint(asset_b.id, [0.99, 0.01, 0.0]),
            ],
        )
    )
    registry._classes["embedding"] = {"fastembed": _FakeEmbedProvider}
    registry._instances["embedding"] = {"fastembed": fake_provider}
    registry._configs["embedding"] = {"fastembed": {}}

    clusters = await find_duplicates(project.id, db, stages=["face"], face_threshold=0.95)

    assert len(clusters) == 1
    cluster = clusters[0]
    assert cluster.cluster_type == "face"
    assert set(cluster.asset_ids) == {asset_a.id, asset_b.id}
    assert cluster.representative_id == asset_b.id


@pytest.mark.asyncio
async def test_duplicate_scan_endpoint_accepts_stages_param(client):
    create = await client.post("/api/projects", json={"name": "Staged Scan"})
    project_id = create.json()["id"]

    from unittest.mock import AsyncMock, patch

    with patch("api.duplicates.queue_duplicate_scan", new_callable=AsyncMock) as mock_scan:
        mock_scan.return_value = "staged-job-1"
        response = await client.post(
            f"/api/projects/{project_id}/duplicates/scan?stages=exact,phash"
        )

    assert response.status_code == 202, response.text
    assert response.json() == {"job_id": "staged-job-1"}
    mock_scan.assert_called_once_with(project_id, stages=["exact", "phash"])


@pytest.mark.asyncio
async def test_exclude_duplicates_marks_assets_as_excluded(db, clean_registry):
    project = await _create_project(db, "exclude-test")
    lower = await _create_asset(
        db,
        project.id,
        "lower-ex.png",
        sha256_hash="exclude-hash",
        composite_score=0.50,
    )
    higher = await _create_asset(
        db,
        project.id,
        "higher-ex.png",
        sha256_hash="exclude-hash",
        composite_score=0.90,
    )

    async with _client_for_db(db) as client:
        response = await client.post(
            f"/api/projects/{project.id}/duplicates/exclude",
            json={"ids": [lower.id]},
        )

    assert response.status_code == 200, response.text
    assert response.json()["excluded"] == 1

    await db.refresh(lower)
    await db.refresh(higher)
    assert lower.export_state == "excluded"
    assert higher.export_state != "excluded"


@pytest.mark.asyncio
async def test_exclude_duplicates_empty_ids_returns_400(client):
    create = await client.post("/api/projects", json={"name": "Exclude Empty"})
    project_id = create.json()["id"]
    response = await client.post(
        f"/api/projects/{project_id}/duplicates/exclude",
        json={"ids": []},
    )
    assert response.status_code == 400


@pytest.mark.asyncio
async def test_get_duplicates_detects_phash_clusters_on_the_fly(db, clean_registry):
    """pHash near-duplicates are detected from stored phash fields without a prior scan."""
    project = await _create_project(db, "phash-onthefly")

    # Use the same fake phash value to simulate a near-match (distance 0)
    asset_a = Asset(
        project_id=project.id,
        filename="a.png",
        filepath="/data/a.png",
        mime_type="image/png",
        sha256_hash="phash-unique-a",
        phash="0000000000000000",
        composite_score=0.70,
    )
    asset_b = Asset(
        project_id=project.id,
        filename="b.png",
        filepath="/data/b.png",
        mime_type="image/png",
        sha256_hash="phash-unique-b",
        phash="0000000000000000",
        composite_score=0.85,
    )
    db.add(asset_a)
    db.add(asset_b)
    await db.flush()

    async with _client_for_db(db) as client:
        response = await client.get(f"/api/projects/{project.id}/duplicates")

    assert response.status_code == 200, response.text
    body = response.json()
    phash_clusters = [c for c in body["clusters"] if c["cluster_type"] == "phash"]
    assert len(phash_clusters) == 1
    ids_in_cluster = {img["id"] for img in phash_clusters[0]["images"]}
    assert ids_in_cluster == {asset_a.id, asset_b.id}
    assert phash_clusters[0]["best_id"] == asset_b.id
