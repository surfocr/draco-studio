from __future__ import annotations

import pytest

from models.asset import Asset
from models.project import Project


async def _create_project(db, name: str = "search") -> Project:
    project = Project(name=name, description="")
    db.add(project)
    await db.flush()
    return project


@pytest.mark.asyncio
async def test_smart_filter_supports_offset_pagination(client, db):
    project = await _create_project(db, "smart-filter-offset")
    for index in range(5):
        db.add(
            Asset(
                project_id=project.id,
                filename=f"asset-{index}.png",
                filepath=f"C:/dataset/asset-{index}.png",
                mime_type="image/png",
                width=512,
                height=512,
                composite_score=0.9,
            )
        )
    await db.commit()

    first = await client.post(
        "/api/search/smart_filter",
        json={
            "project_id": project.id,
            "rules": [{"field": "composite_score", "op": "gte", "value": 0.5}],
            "limit": 2,
            "offset": 0,
        },
    )
    second = await client.post(
        "/api/search/smart_filter",
        json={
            "project_id": project.id,
            "rules": [{"field": "composite_score", "op": "gte", "value": 0.5}],
            "limit": 2,
            "offset": 2,
        },
    )

    assert first.status_code == 200, first.text
    assert second.status_code == 200, second.text
    first_ids = [item["id"] for item in first.json()]
    second_ids = [item["id"] for item in second.json()]
    assert len(first_ids) == 2
    assert len(second_ids) == 2
    assert set(first_ids).isdisjoint(second_ids)
