from __future__ import annotations

import pytest


@pytest.mark.asyncio
async def test_storage_info_returns_backend_paths(client):
    response = await client.get("/api/admin/storage-info")

    assert response.status_code == 200, response.text
    body = response.json()
    assert "storage_path" in body
    assert "data_dir" in body
    assert "qdrant_path" in body
