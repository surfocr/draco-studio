from __future__ import annotations

import pytest

from models.asset import Asset
from models.project import Project
from services.ranking import RankingService


def _make_asset(
    project_id: str,
    filename: str,
    *,
    mu: float,
    sigma: float,
    comparisons: int = 0,
    composite: float = 0.8,
    usefulness: float = 0.8,
    technical: float = 0.8,
    face: float = 0.8,
) -> Asset:
    return Asset(
        project_id=project_id,
        filename=filename,
        filepath=f"C:/dataset/{filename}",
        mime_type="image/png",
        width=1024,
        height=1024,
        trueskill_mu=mu,
        trueskill_sigma=sigma,
        ranking_comparisons_count=comparisons,
        composite_score=composite,
        training_usefulness=usefulness,
        technical_quality=technical,
        face_quality=face,
        face_count=1,
    )


@pytest.mark.asyncio
async def test_create_ranking_session_persists_scope_and_strategy(client, db):
    project = Project(name="ranking-session", description="")
    db.add(project)
    await db.flush()

    assets = [
        _make_asset(project.id, "a.png", mu=30.0, sigma=5.0),
        _make_asset(project.id, "b.png", mu=29.5, sigma=5.0),
        _make_asset(project.id, "c.png", mu=12.0, sigma=2.0),
    ]
    db.add_all(assets)
    await db.commit()

    response = await client.post(
        f"/api/projects/{project.id}/ranking/sessions",
        json={
            "name": "Subset ranking",
            "engine": "openskill",
            "scope": "custom",
            "asset_ids": [assets[0].id, assets[1].id],
            "strategy": "balanced",
        },
    )

    assert response.status_code == 201, response.text
    payload = response.json()
    assert payload["asset_scope"] == "custom"
    assert payload["selection_strategy"] == "balanced"
    assert payload["asset_ids_count"] == 2

    sessions = await client.get(f"/api/projects/{project.id}/ranking/sessions")
    assert sessions.status_code == 200, sessions.text
    listed = sessions.json()
    assert listed[0]["asset_scope"] == "custom"
    assert listed[0]["selection_strategy"] == "balanced"
    assert listed[0]["asset_ids_count"] == 2


@pytest.mark.asyncio
async def test_get_next_pair_respects_scoped_asset_ids(client, db):
    project = Project(name="ranking-scope", description="")
    db.add(project)
    await db.flush()

    assets = [
        _make_asset(project.id, "a.png", mu=30.0, sigma=5.0),
        _make_asset(project.id, "b.png", mu=29.8, sigma=5.0),
        _make_asset(project.id, "c.png", mu=10.0, sigma=1.0),
    ]
    db.add_all(assets)
    await db.commit()

    create_response = await client.post(
        f"/api/projects/{project.id}/ranking/sessions",
        json={
            "name": "Scoped session",
            "engine": "openskill",
            "scope": "custom",
            "asset_ids": [assets[0].id, assets[1].id],
            "strategy": "balanced",
        },
    )
    session_id = create_response.json()["id"]

    pair_response = await client.get(f"/api/ranking/sessions/{session_id}/next-pair")
    assert pair_response.status_code == 200, pair_response.text
    pair = pair_response.json()
    returned_ids = {pair["asset_a"]["id"], pair["asset_b"]["id"]}
    assert returned_ids == {assets[0].id, assets[1].id}


@pytest.mark.asyncio
async def test_scoped_ranking_session_requires_asset_ids(client, db):
    project = Project(name="ranking-empty-scope", description="")
    db.add(project)
    await db.commit()

    response = await client.post(
        f"/api/projects/{project.id}/ranking/sessions",
        json={
            "name": "Broken scoped session",
            "engine": "openskill",
            "scope": "selected",
            "asset_ids": [],
            "strategy": "balanced",
        },
    )

    assert response.status_code == 422
    assert "asset_ids" in response.text


@pytest.mark.asyncio
async def test_ranking_skip_and_undo_routes_work(client, db):
    project = Project(name="ranking-routes", description="")
    db.add(project)
    await db.flush()

    assets = [
        _make_asset(project.id, "a.png", mu=25.0, sigma=8.333),
        _make_asset(project.id, "b.png", mu=24.9, sigma=8.333),
        _make_asset(project.id, "c.png", mu=10.0, sigma=1.0),
    ]
    db.add_all(assets)
    await db.commit()

    session_response = await client.post(
        f"/api/projects/{project.id}/ranking/sessions",
        json={
            "name": "Routes",
            "engine": "openskill",
            "scope": "all",
            "strategy": "balanced",
        },
    )
    assert session_response.status_code == 201, session_response.text
    session_id = session_response.json()["id"]

    pair_response = await client.get(f"/api/ranking/sessions/{session_id}/next-pair")
    assert pair_response.status_code == 200, pair_response.text
    pair = pair_response.json()

    skip_response = await client.post(
        f"/api/ranking/sessions/{session_id}/skip",
        json={
            "asset_a_id": pair["asset_a"]["id"],
            "asset_b_id": pair["asset_b"]["id"],
        },
    )
    assert skip_response.status_code == 200, skip_response.text
    assert skip_response.json()["skipped_pairs_count"] == 1

    compare_response = await client.post(
        f"/api/ranking/sessions/{session_id}/compare",
        json={
            "winner_id": assets[0].id,
            "loser_id": assets[2].id,
            "draw": False,
        },
    )
    assert compare_response.status_code == 200, compare_response.text

    undo_response = await client.post(f"/api/ranking/sessions/{session_id}/undo")
    assert undo_response.status_code == 200, undo_response.text
    assert undo_response.json()["total_comparisons"] == 0


@pytest.mark.asyncio
async def test_balanced_strategy_prefers_closest_uncompared_pair(db):
    project = Project(name="ranking-balanced", description="")
    db.add(project)
    await db.flush()

    close_a = _make_asset(project.id, "close-a.png", mu=26.0, sigma=5.0, comparisons=0)
    close_b = _make_asset(project.id, "close-b.png", mu=25.7, sigma=5.0, comparisons=0)
    far_c = _make_asset(project.id, "far-c.png", mu=12.0, sigma=2.0, comparisons=0)
    far_d = _make_asset(project.id, "far-d.png", mu=40.0, sigma=2.0, comparisons=0)
    db.add_all([close_a, close_b, far_c, far_d])
    await db.flush()

    service = RankingService()
    session = await service.create_session(
        project.id,
        engine="openskill",
        scope="all",
        asset_ids=[],
        db=db,
        name="Balanced",
        strategy="balanced",
    )
    await db.commit()

    pair = await service.get_next_pair(session.id, db, strategy="balanced")
    assert pair is not None
    assert {pair[0].id, pair[1].id} == {close_a.id, close_b.id}


@pytest.mark.asyncio
async def test_balanced_strategy_skips_previous_comparisons(db):
    project = Project(name="ranking-skip", description="")
    db.add(project)
    await db.flush()

    assets = [
        _make_asset(project.id, "a.png", mu=26.0, sigma=5.0),
        _make_asset(project.id, "b.png", mu=25.8, sigma=5.0),
        _make_asset(project.id, "c.png", mu=25.6, sigma=5.0),
    ]
    db.add_all(assets)
    await db.flush()

    service = RankingService()
    session = await service.create_session(
        project.id,
        engine="openskill",
        scope="all",
        asset_ids=[],
        db=db,
        name="Balanced history",
        strategy="balanced",
    )
    await db.flush()
    await service.record_comparison(session.id, assets[0].id, assets[1].id, False, db)
    await db.commit()

    pair = await service.get_next_pair(session.id, db, strategy="balanced")
    assert pair is not None
    assert {pair[0].id, pair[1].id} != {assets[0].id, assets[1].id}


@pytest.mark.asyncio
async def test_skip_pair_persists_and_removes_pair_from_queue(db):
    project = Project(name="ranking-skip-persist", description="")
    db.add(project)
    await db.flush()

    assets = [
        _make_asset(project.id, "a.png", mu=30.0, sigma=5.0),
        _make_asset(project.id, "b.png", mu=29.9, sigma=5.0),
        _make_asset(project.id, "c.png", mu=10.0, sigma=1.0),
    ]
    db.add_all(assets)
    await db.flush()

    service = RankingService()
    session = await service.create_session(
        project.id,
        engine="openskill",
        scope="all",
        asset_ids=[asset.id for asset in assets],
        db=db,
        name="Skip queue",
        strategy="balanced",
    )
    await db.flush()

    first_pair = await service.get_next_pair(session.id, db, strategy="balanced")
    assert first_pair is not None

    updated = await service.skip_pair(session.id, first_pair[0].id, first_pair[1].id, db)
    assert len(updated.skipped_pairs or []) == 1

    second_pair = await service.get_next_pair(session.id, db, strategy="balanced")
    assert second_pair is not None
    assert {second_pair[0].id, second_pair[1].id} != {first_pair[0].id, first_pair[1].id}


@pytest.mark.asyncio
async def test_revert_last_comparison_replays_session_ratings(db):
    project = Project(name="ranking-revert", description="")
    db.add(project)
    await db.flush()

    assets = [
        _make_asset(project.id, "a.png", mu=25.0, sigma=8.333, comparisons=0),
        _make_asset(project.id, "b.png", mu=25.0, sigma=8.333, comparisons=0),
    ]
    db.add_all(assets)
    await db.flush()

    service = RankingService()
    session = await service.create_session(
        project.id,
        engine="openskill",
        scope="all",
        asset_ids=[asset.id for asset in assets],
        db=db,
        name="Revertable",
        strategy="uncertainty",
    )
    await db.flush()

    before = {
        asset.id: (
            asset.trueskill_mu,
            asset.trueskill_sigma,
            asset.elo_rating,
            asset.ranking_comparisons_count,
        )
        for asset in assets
    }

    await service.record_comparison(session.id, assets[0].id, assets[1].id, False, db)
    await db.flush()

    assert assets[0].ranking_comparisons_count == 1
    assert assets[1].ranking_comparisons_count == 1

    reverted = await service.revert_last_comparison(session.id, db)
    assert reverted.total_comparisons == 0

    await db.refresh(assets[0])
    await db.refresh(assets[1])

    after = {
        asset.id: (
            asset.trueskill_mu,
            asset.trueskill_sigma,
            asset.elo_rating,
            asset.ranking_comparisons_count,
        )
        for asset in assets
    }
    assert after == before
