from __future__ import annotations

import pytest
from sqlalchemy import select

from models.asset import Asset
from models.face import IdentityCluster
from models.project import Project
from providers.registry import get_registry
from services.face_clustering import run_face_clustering


async def _create_project(db, name: str = "faces") -> Project:
    project = Project(name=name, description="")
    db.add(project)
    await db.flush()
    return project


async def _create_asset(
    db,
    project_id: str,
    filename: str,
    *,
    composite_score: float,
    vector_id: str,
) -> Asset:
    asset = Asset(
        project_id=project_id,
        filename=filename,
        filepath=f"C:/dataset/{filename}",
        mime_type="image/png",
        width=1024,
        height=1024,
        sha256_hash=filename,
        composite_score=composite_score,
        technical_quality=composite_score,
        training_usefulness=composite_score,
        face_embedding_id=vector_id,
    )
    db.add(asset)
    await db.flush()
    return asset


class _FakeCollectionList:
    def __init__(self, names: list[str]):
        self.collections = [type("Collection", (), {"name": name}) for name in names]


class _FakePoint:
    def __init__(self, asset_id: str, vector: list[float], face_index: int = 0):
        self.id = f"point-{asset_id}-{face_index}"
        self.payload = {"asset_id": asset_id, "face_index": face_index}
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


@pytest.fixture
def clean_registry():
    registry = get_registry()
    registry._classes.clear()
    registry._instances.clear()
    registry._configs.clear()
    yield
    registry._classes.clear()
    registry._instances.clear()
    registry._configs.clear()


@pytest.mark.asyncio
async def test_face_clustering_prefers_highest_quality_thumbnail(db, clean_registry):
    from config import settings

    project = await _create_project(db, "identity-quality")
    lower = await _create_asset(
        db,
        project.id,
        "lower.png",
        composite_score=0.51,
        vector_id="face-lower",
    )
    higher = await _create_asset(
        db,
        project.id,
        "higher.png",
        composite_score=0.94,
        vector_id="face-higher",
    )
    await db.commit()

    registry = get_registry()
    fake_provider = _FakeEmbedProvider(
        _FakeQdrant(
            settings.QDRANT_FACE_COLLECTION,
            [
                _FakePoint(lower.id, [1.0, 0.0, 0.0]),
                _FakePoint(higher.id, [0.99, 0.01, 0.0]),
            ],
        )
    )
    registry._classes["embedding"] = {"fastembed": _FakeEmbedProvider}
    registry._instances["embedding"] = {"fastembed": fake_provider}
    registry._configs["embedding"] = {"fastembed": {}}

    result = await run_face_clustering(project.id, db)

    assert result["clusters"] == 1
    clusters = (await db.execute(select(IdentityCluster))).scalars().all()
    assert len(clusters) == 1
    assert clusters[0].thumbnail_asset_id == higher.id
