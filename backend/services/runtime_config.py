"""Project-aware runtime configuration and provider resolution."""
from __future__ import annotations

import copy
from dataclasses import dataclass
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from models.preferences import UserPreferences
from models.project import Project
from models.project_runtime_config import ProjectRuntimeConfig
from models.provider_config import ProviderConfig
from providers.registry import get_registry

VALID_RUNTIME_MODES = {"local", "hybrid", "hosted"}

TASK_SPECS: dict[str, dict[str, Any]] = {
    "caption": {
        "label": "Captioning",
        "provider_type": "caption",
        "description": "Primary image caption generation for training captions.",
        "defaults": ["ollama", "lmstudio", "joycaption", "gemini", "openai", "moondream"],
    },
    "ranking_explanation": {
        "label": "Ranking Explanations",
        "provider_type": "caption",
        "description": "Vision-language model for pairwise ranking explanations and AI judging.",
        "defaults": ["gemini", "ollama", "lmstudio", "openai", "qwen_vl", "moondream"],
    },
    "dataset_coach": {
        "label": "Dataset Coach",
        "provider_type": "caption",
        "description": "Vision-language model for project-level coaching and QA guidance.",
        "defaults": ["gemini", "ollama", "lmstudio", "openai", "qwen_vl", "moondream"],
    },
    "embedding": {
        "label": "Embeddings",
        "provider_type": "embedding",
        "description": "Image embeddings for search, retrieval, and near-duplicate detection.",
        "defaults": ["fastembed"],
    },
    "face_detection": {
        "label": "Face Detection",
        "provider_type": "face_detection",
        "description": "Face detection and face embedding extraction.",
        "defaults": ["insightface"],
    },
    "scene_understanding": {
        "label": "Scene Understanding",
        "provider_type": "scene_understanding",
        "description": "Scene, object, and lighting analysis.",
        "defaults": ["clip_scene"],
    },
    "quality": {
        "label": "Quality Scoring",
        "provider_type": "quality",
        "description": "Composite technical and training-value scoring.",
        "defaults": ["composite", "laion_aesthetic"],
    },
    "ranking_engine": {
        "label": "Ranking Engine",
        "provider_type": "ranking",
        "description": "Pairwise ranking engine for manual comparisons.",
        "defaults": ["openskill", "elo"],
    },
    "outpainting": {
        "label": "Outpainting",
        "provider_type": "ai_outpainting",
        "description": "Outpainting and aspect-ratio adaptation.",
        "defaults": ["comfyui"],
    },
    "image_editor": {
        "label": "Image Editor",
        "provider_type": "ai_image_editor",
        "description": "Editing and augmentation provider.",
        "defaults": ["basic_editor", "comfyui"],
    },
}

DEFAULT_TASK_PROVIDER_OPTIONS: dict[str, dict[str, Any]] = {
    "caption": {
        "model": "llava:13b",
        "temperature": 0.25,
        "context_length": 4096,
        "max_tokens": 512,
        "timeout": 120,
        "batch_size": 1,
        "concurrency": 1,
    },
    "ranking_explanation": {
        "model": "llava:13b",
        "temperature": 0.1,
        "context_length": 4096,
        "max_tokens": 1024,
        "timeout": 120,
        "batch_size": 1,
        "concurrency": 1,
    },
    "dataset_coach": {
        "model": "llava:13b",
        "temperature": 0.2,
        "context_length": 4096,
        "max_tokens": 1024,
        "timeout": 120,
        "batch_size": 1,
        "concurrency": 1,
    },
}


@dataclass
class ResolvedProvider:
    provider_name: str | None
    provider: Any | None
    options: dict[str, Any]
    candidates: list[str]


def _normalized_task_map(raw: dict | None) -> dict[str, str]:
    if not isinstance(raw, dict):
        return {}
    return {
        str(key): str(value)
        for key, value in raw.items()
        if key and value
    }


def _normalized_options_map(raw: dict | None) -> dict[str, dict[str, Any]]:
    if not isinstance(raw, dict):
        return {}
    output: dict[str, dict[str, Any]] = {}
    for key, value in raw.items():
        if isinstance(value, dict):
            output[str(key)] = dict(value)
    return output


def _default_runtime_options() -> dict[str, dict[str, Any]]:
    return copy.deepcopy(DEFAULT_TASK_PROVIDER_OPTIONS)


async def get_project_runtime_config(
    db: AsyncSession,
    project_id: str,
) -> ProjectRuntimeConfig | None:
    project = await db.get(Project, project_id)
    if project is None:
        raise LookupError(f"Project {project_id} not found")

    cfg = await db.get(ProjectRuntimeConfig, project_id)
    if cfg is not None:
        if cfg.task_provider_overrides is None:
            cfg.task_provider_overrides = {}
        if cfg.task_provider_options is None:
            cfg.task_provider_options = _default_runtime_options()
        if cfg.benchmark_preferences is None:
            cfg.benchmark_preferences = {}
    return cfg


def build_default_runtime_config(project_id: str) -> ProjectRuntimeConfig:
    return ProjectRuntimeConfig(
        project_id=project_id,
        runtime_mode="local",
        task_provider_overrides={},
        task_provider_options=_default_runtime_options(),
        benchmark_preferences={},
    )


async def get_or_create_project_runtime_config(
    db: AsyncSession,
    project_id: str,
) -> ProjectRuntimeConfig:
    cfg = await get_project_runtime_config(db, project_id)
    if cfg is not None:
        return cfg

    cfg = build_default_runtime_config(project_id)
    db.add(cfg)
    await db.flush()
    return cfg


async def get_global_task_defaults(db: AsyncSession) -> dict[str, str]:
    prefs = await db.get(UserPreferences, 1)
    if prefs is None:
        return {}

    defaults = {}
    if prefs.default_caption_provider:
        defaults["caption"] = prefs.default_caption_provider

    extra = prefs.extra or {}
    task_defaults = extra.get("task_provider_defaults", {}) if isinstance(extra, dict) else {}
    if isinstance(task_defaults, dict):
        defaults.update(_normalized_task_map(task_defaults))
    return defaults


async def resolve_provider_for_task(
    db: AsyncSession,
    project_id: str | None,
    task_key: str,
    explicit_provider_name: str | None = None,
    require_available: bool = True,
) -> ResolvedProvider:
    spec = TASK_SPECS.get(task_key)
    if spec is None:
        raise ValueError(f"Unknown runtime task '{task_key}'")

    registry = get_registry()
    provider_type = str(spec["provider_type"])
    candidates: list[str] = []

    if explicit_provider_name and explicit_provider_name != "auto":
        candidates.append(explicit_provider_name)

    config: ProjectRuntimeConfig | None = None
    if project_id:
        config = await get_project_runtime_config(db, project_id)
        overrides = _normalized_task_map(config.task_provider_overrides if config else {})
        selected = overrides.get(task_key)
        if selected:
            candidates.append(selected)

    global_defaults = await get_global_task_defaults(db)
    global_selected = global_defaults.get(task_key)
    if global_selected:
        candidates.append(global_selected)

    default_row_result = await db.execute(
        select(ProviderConfig.provider_name)
        .where(
            ProviderConfig.provider_type == provider_type,
            ProviderConfig.is_enabled.is_(True),
            ProviderConfig.is_default.is_(True),
        )
        .order_by(ProviderConfig.updated_at.desc())
    )
    candidates.extend(str(name) for name in default_row_result.scalars().all())
    candidates.extend(spec.get("defaults", []))
    candidates.extend(registry.list_available(provider_type))

    deduped: list[str] = []
    for candidate in candidates:
        if candidate and candidate not in deduped:
            deduped.append(candidate)

    options = dict(_default_runtime_options().get(task_key, {}))
    if config:
        task_options = _normalized_options_map(config.task_provider_options).get(task_key, {})
        options.update(task_options)

    for candidate in deduped:
        provider = registry.get(provider_type, candidate)
        if provider is None:
            continue
        if require_available:
            try:
                if not await registry.check_available(provider_type, candidate):
                    continue
            except Exception:
                continue
        return ResolvedProvider(
            provider_name=candidate,
            provider=provider,
            options=options,
            candidates=deduped,
        )

    return ResolvedProvider(
        provider_name=None,
        provider=None,
        options=options,
        candidates=deduped,
    )


async def build_runtime_catalog(
    db: AsyncSession,
    project_id: str,
) -> list[dict[str, Any]]:
    cfg = await get_project_runtime_config(db, project_id)
    if cfg is None:
        cfg = build_default_runtime_config(project_id)
    overrides = _normalized_task_map(cfg.task_provider_overrides)
    catalog: list[dict[str, Any]] = []
    registry = get_registry()

    for task_key, spec in TASK_SPECS.items():
        provider_type = str(spec["provider_type"])
        resolved = await resolve_provider_for_task(
            db,
            project_id=project_id,
            task_key=task_key,
            explicit_provider_name=None,
            require_available=False,
        )
        catalog.append(
            {
                "task_key": task_key,
                "label": spec["label"],
                "provider_type": provider_type,
                "description": spec["description"],
                "selected_provider": overrides.get(task_key),
                "effective_provider": resolved.provider_name,
                "available_providers": registry.list_available(provider_type),
            }
        )
    return catalog
