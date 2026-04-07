from __future__ import annotations

import pytest

from models.asset import Asset
from models.caption import CaptionVersion
from models.project import Project
from services.coach import DatasetCoach


@pytest.mark.asyncio
async def test_coach_normalize_captions_applies_real_caption_normalization(client, db):
    project = Project(name="coach-normalize", description="")
    db.add(project)
    await db.flush()

    asset = Asset(
        project_id=project.id,
        filename="sample.png",
        filepath="C:/dataset/sample.png",
        mime_type="image/png",
        width=512,
        height=512,
    )
    db.add(asset)
    await db.flush()

    caption = CaptionVersion(
        asset_id=asset.id,
        text="  trigger,,portrait  ",
        style="training_literal",
        provider="test",
        model="test",
        is_active=True,
    )
    db.add(caption)
    await db.flush()
    asset.active_caption_id = caption.id
    await db.commit()

    response = await client.post(
        f"/api/projects/{project.id}/coach/apply/normalize_captions",
        json={"asset_ids": [asset.id]},
    )

    assert response.status_code == 200, response.text
    assert response.json() == {"affected": 1, "action": "normalize_captions"}

    await db.refresh(asset)
    await db.refresh(caption)
    assert asset.active_caption_id != caption.id

    normalized_caption = await db.get(CaptionVersion, asset.active_caption_id)
    assert normalized_caption is not None
    assert normalized_caption.text == "trigger, portrait"
    assert normalized_caption.is_active is True


@pytest.mark.asyncio
async def test_coach_balances_keep_first_with_next_best_candidates(db):
    project = Project(name="coach-balance", description="")
    db.add(project)
    await db.flush()

    assets = [
        Asset(
            project_id=project.id,
            filename="closeup-a.png",
            filepath="C:/dataset/closeup-a.png",
            mime_type="image/png",
            width=1024,
            height=1024,
            shot_type="closeup",
            dominant_emotion="neutral",
            composite_score=0.95,
            training_usefulness=0.95,
            technical_quality=0.92,
            face_quality=0.95,
            face_count=1,
        ),
        Asset(
            project_id=project.id,
            filename="closeup-b.png",
            filepath="C:/dataset/closeup-b.png",
            mime_type="image/png",
            width=1024,
            height=1024,
            shot_type="closeup",
            dominant_emotion="neutral",
            composite_score=0.90,
            training_usefulness=0.90,
            technical_quality=0.89,
            face_quality=0.91,
            face_count=1,
        ),
        Asset(
            project_id=project.id,
            filename="wide-smile.png",
            filepath="C:/dataset/wide-smile.png",
            mime_type="image/png",
            width=1024,
            height=1400,
            shot_type="wide",
            dominant_emotion="happy",
            head_pose_yaw=32.0,
            is_indoor=False,
            composite_score=0.74,
            training_usefulness=0.82,
            technical_quality=0.78,
            face_quality=0.76,
            face_count=1,
        ),
    ]
    db.add_all(assets)
    await db.commit()

    report = await DatasetCoach().analyze(project.id, db)

    assert len(report.keep_first) == 3
    # recommended_selection contains all 3 assets (any order), starting with the
    # highest-quality asset.  The diversity-aware ranker chooses:
    #   1. closeup-a (highest quality)
    #   2. wide-smile (new shot type, angle, expression, background)
    #   3. closeup-b (remaining)
    assert set(report.recommended_selection) == {asset.id for asset in assets}
    assert report.keep_first[0] == assets[0].id
    assert report.keep_first[1] == assets[2].id
    assert report.keep_first[2] == assets[1].id
    assert report.next_best == []
    assert report.selection_target_count == 3


@pytest.mark.asyncio
async def test_coach_next_best_starts_after_recommended_selection_target(db):
    project = Project(name="coach-selection-window", description="")
    db.add(project)
    await db.flush()

    assets: list[Asset] = []
    for index in range(35):
        asset = Asset(
            project_id=project.id,
            filename=f"asset-{index:02d}.png",
            filepath=f"C:/dataset/asset-{index:02d}.png",
            mime_type="image/png",
            width=1024,
            height=1024 + index,
            shot_type="closeup" if index % 3 else "medium",
            dominant_emotion="neutral" if index % 4 else "happy",
            is_indoor=(index % 2 == 0),
            composite_score=max(0.1, 0.99 - index * 0.01),
            training_usefulness=max(0.1, 0.98 - index * 0.01),
            technical_quality=max(0.1, 0.97 - index * 0.01),
            face_quality=max(0.1, 0.96 - index * 0.01),
            face_count=1,
        )
        assets.append(asset)
    db.add_all(assets)
    await db.commit()

    report = await DatasetCoach().analyze(project.id, db)

    assert report.selection_target_count == 30
    assert len(report.recommended_selection) == 30
    assert len(report.next_best) == 5
    assert set(report.recommended_selection).isdisjoint(report.next_best)
    assert report.keep_first == report.recommended_selection[:10]
