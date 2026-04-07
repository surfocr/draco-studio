"""Project runtime configuration endpoints."""
from __future__ import annotations

from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from database import get_db
from services.runtime_config import (
    TASK_SPECS,
    VALID_RUNTIME_MODES,
    build_runtime_catalog,
    build_default_runtime_config,
    get_project_runtime_config,
    get_or_create_project_runtime_config,
    resolve_provider_for_task,
)

router = APIRouter(prefix="/api/projects", tags=["runtime"])


class RuntimeTaskCatalogEntry(BaseModel):
    task_key: str
    label: str
    provider_type: str
    description: str
    selected_provider: str | None
    effective_provider: str | None
    available_providers: list[str]


class ProjectRuntimeConfigResponse(BaseModel):
    project_id: str
    runtime_mode: str
    task_provider_overrides: dict[str, str]
    task_provider_options: dict[str, dict[str, Any]]
    benchmark_preferences: dict[str, Any]
    task_catalog: list[RuntimeTaskCatalogEntry]


class ProjectRuntimeConfigUpdate(BaseModel):
    runtime_mode: Literal["local", "hybrid", "hosted"] | None = None
    task_provider_overrides: dict[str, str | None] | None = None
    task_provider_options: dict[str, dict[str, Any]] | None = None
    benchmark_preferences: dict[str, Any] | None = None


def _validate_task_overrides(overrides: dict[str, str | None]) -> dict[str, str]:
    validated: dict[str, str] = {}
    for task_key, provider_name in overrides.items():
        if task_key not in TASK_SPECS:
            raise HTTPException(status_code=422, detail=f"Unknown runtime task '{task_key}'")
        if provider_name:
            validated[task_key] = provider_name
    return validated


@router.get("/{project_id}/runtime", response_model=ProjectRuntimeConfigResponse)
async def get_runtime_config_endpoint(
    project_id: str,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> ProjectRuntimeConfigResponse:
    try:
        cfg = await get_project_runtime_config(db, project_id)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    if cfg is None:
        cfg = build_default_runtime_config(project_id)

    catalog = await build_runtime_catalog(db, project_id)
    return ProjectRuntimeConfigResponse(
        project_id=cfg.project_id,
        runtime_mode=cfg.runtime_mode,
        task_provider_overrides=dict(cfg.task_provider_overrides or {}),
        task_provider_options=dict(cfg.task_provider_options or {}),
        benchmark_preferences=dict(cfg.benchmark_preferences or {}),
        task_catalog=[RuntimeTaskCatalogEntry.model_validate(item) for item in catalog],
    )


@router.patch("/{project_id}/runtime", response_model=ProjectRuntimeConfigResponse)
async def update_project_runtime_config(
    project_id: str,
    body: ProjectRuntimeConfigUpdate,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> ProjectRuntimeConfigResponse:
    try:
        cfg = await get_or_create_project_runtime_config(db, project_id)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc))

    if body.runtime_mode is not None:
        if body.runtime_mode not in VALID_RUNTIME_MODES:
            raise HTTPException(status_code=422, detail="Invalid runtime mode")
        cfg.runtime_mode = body.runtime_mode

    if body.task_provider_overrides is not None:
        cfg.task_provider_overrides = _validate_task_overrides(body.task_provider_overrides)

    if body.task_provider_options is not None:
        cleaned_options: dict[str, dict[str, Any]] = {}
        for task_key, task_options in body.task_provider_options.items():
            if task_key not in TASK_SPECS:
                raise HTTPException(status_code=422, detail=f"Unknown runtime task '{task_key}'")
            cleaned_options[task_key] = dict(task_options)
        cfg.task_provider_options = cleaned_options

    if body.benchmark_preferences is not None:
        cfg.benchmark_preferences = dict(body.benchmark_preferences)

    await db.flush()
    catalog = await build_runtime_catalog(db, project_id)
    return ProjectRuntimeConfigResponse(
        project_id=cfg.project_id,
        runtime_mode=cfg.runtime_mode,
        task_provider_overrides=dict(cfg.task_provider_overrides or {}),
        task_provider_options=dict(cfg.task_provider_options or {}),
        benchmark_preferences=dict(cfg.benchmark_preferences or {}),
        task_catalog=[RuntimeTaskCatalogEntry.model_validate(item) for item in catalog],
    )


@router.get("/{project_id}/runtime/resolve/{task_key}")
async def resolve_project_runtime_provider(
    project_id: str,
    task_key: str,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> dict[str, Any]:
    try:
        resolved = await resolve_provider_for_task(db, project_id, task_key, require_available=False)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))

    return {
        "task_key": task_key,
        "provider_name": resolved.provider_name,
        "options": resolved.options,
        "candidates": resolved.candidates,
    }
