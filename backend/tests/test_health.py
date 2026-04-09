"""Health endpoint smoke tests."""
from __future__ import annotations

import builtins
import pytest
from fastapi import APIRouter
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select

from models.provider_config import ProviderConfig
from providers.base import CaptionResult


@pytest.mark.asyncio
async def test_health_endpoint(client):
    """GET /api/health returns 200 with status ok."""
    r = await client.get("/api/health")
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "ok"


@pytest.mark.asyncio
async def test_health_endpoint_returns_request_id_header(client):
    r = await client.get("/api/health", headers={"X-Request-ID": "health-test-id"})
    assert r.status_code == 200
    assert r.headers["x-request-id"] == "health-test-id"


@pytest.mark.asyncio
async def test_unhandled_exceptions_include_request_id():
    from main import app

    router = APIRouter()

    @router.get("/api/test-crash-request-id")
    async def _boom():
        raise RuntimeError("boom")

    app.include_router(router)

    async with AsyncClient(
        transport=ASGITransport(app=app, raise_app_exceptions=False),
        base_url="http://test",
    ) as client:
        r = await client.get(
            "/api/test-crash-request-id",
            headers={"X-Request-ID": "error-test-id"},
        )

    assert r.status_code == 500
    body = r.json()
    assert body["detail"] == "Internal server error"
    assert body["request_id"] == "error-test-id"
    assert r.headers["x-request-id"] == "error-test-id"


@pytest.mark.asyncio
async def test_providers_list(client):
    """GET /api/providers returns a providers dict."""
    r = await client.get("/api/providers")
    assert r.status_code == 200
    body = r.json()
    assert "providers" in body
    assert isinstance(body["providers"], dict)


@pytest.mark.asyncio
async def test_provider_configs_endpoint(client):
    r = await client.get("/api/providers/configs")
    assert r.status_code == 200
    body = r.json()
    assert "configs" in body
    assert isinstance(body["configs"], dict)


@pytest.mark.asyncio
async def test_provider_config_rejects_secret_like_keys(client):
    response = await client.post(
        "/api/providers/caption/config",
        json={"config": {"provider_name": "openai", "api_key": "plaintext-secret"}},
    )

    assert response.status_code == 400
    assert "must be saved via /api/providers/api-key" in response.json()["detail"]


@pytest.mark.asyncio
async def test_save_api_key_rejects_blank_values(client):
    response = await client.post(
        "/api/providers/api-key",
        json={
            "provider_type": "caption",
            "provider_name": "openai",
            "api_key": "   ",
        },
    )

    assert response.status_code == 400
    assert response.json()["detail"] == "API key must not be empty"


def test_get_fernet_reports_missing_cryptography(monkeypatch, caplog):
    """When `cryptography` is unavailable, _get_fernet returns None and logs a warning.

    Encrypted API key storage degrades gracefully rather than crashing the server —
    callers must handle the None sentinel and surface a user-facing error.
    """
    import logging

    from api import providers as providers_api

    real_import = builtins.__import__

    def fake_import(name, globals=None, locals=None, fromlist=(), level=0):
        if name == "cryptography.fernet":
            raise ImportError("No module named cryptography")
        return real_import(name, globals, locals, fromlist, level)

    monkeypatch.setattr(builtins, "__import__", fake_import)
    monkeypatch.setenv("DRACO_SECRET_KEY", "test-secret")

    with caplog.at_level(logging.WARNING, logger="api.providers"):
        result = providers_api._get_fernet()

    assert result is None
    assert any("cryptography" in rec.message for rec in caplog.records)


def test_caption_result_supports_provider_errors():
    result = CaptionResult(
        text="",
        style="natural",
        provider="qwen_vl",
        model="test-model",
        error="load failed",
    )
    assert result.error == "load failed"


@pytest.mark.asyncio
async def test_local_caption_provider_health_checks_do_not_require_optional_deps():
    from providers.caption.moondream import MoondreamProvider
    from providers.caption.qwen_vl import QwenVLProvider

    moondream_health = await MoondreamProvider().health_check()
    qwen_health = await QwenVLProvider().health_check()

    assert "ok" in moondream_health
    assert "details" in moondream_health
    assert moondream_health["details"]["model"] == "vikhyatk/moondream2"

    assert "ok" in qwen_health
    assert "details" in qwen_health
    assert qwen_health["details"]["model"] == "Qwen/Qwen2.5-VL-7B-Instruct"


@pytest.mark.asyncio
async def test_provider_config_save_persists_non_secret_config(client, db):
    response = await client.post(
        "/api/providers/editing/config",
        json={
            "config": {
                "provider_name": "comfyui",
                "base_url": "http://127.0.0.1:8188",
            }
        },
    )

    assert response.status_code == 200, response.text
    row = (
        await db.execute(
            select(ProviderConfig).where(
                ProviderConfig.provider_type == "editing",
                ProviderConfig.provider_name == "comfyui",
            )
        )
    ).scalar_one()
    assert row.config["base_url"] == "http://127.0.0.1:8188"
