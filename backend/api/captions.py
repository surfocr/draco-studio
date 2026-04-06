"""Captions router — complete implementation."""
from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from database import get_db
from services.caption import get_caption_service

router = APIRouter(prefix="/api", tags=["captions"])


# ── Pydantic schemas ──────────────────────────────────────────────────────────

class CaptionVersionResponse(BaseModel):
    id: str
    asset_id: str
    text: str
    style: str
    provider: str
    model: str | None
    confidence: float | None
    latency_ms: int | None
    is_edited: bool
    is_active: bool
    created_at: str

    model_config = {"from_attributes": True}

    @classmethod
    def from_orm(cls, obj: object) -> "CaptionVersionResponse":
        created = getattr(obj, "created_at", None)
        return cls(
            id=obj.id,  # type: ignore[attr-defined]
            asset_id=obj.asset_id,  # type: ignore[attr-defined]
            text=obj.text,  # type: ignore[attr-defined]
            style=obj.style,  # type: ignore[attr-defined]
            provider=obj.provider or "",  # type: ignore[attr-defined]
            model=obj.model,  # type: ignore[attr-defined]
            confidence=obj.confidence,  # type: ignore[attr-defined]
            latency_ms=obj.latency_ms,  # type: ignore[attr-defined]
            is_edited=obj.is_edited or False,  # type: ignore[attr-defined]
            is_active=obj.is_active or False,  # type: ignore[attr-defined]
            created_at=created.isoformat() if created else "",
        )


class GenerateCaptionRequest(BaseModel):
    provider: str
    style: str = "natural"
    options: dict | None = None
    set_active: bool = True


class CompareProvidersRequest(BaseModel):
    providers: list[str] = Field(min_length=2)
    style: str = "natural"
    options: dict | None = None


class ActivateCaptionRequest(BaseModel):
    pass  # version_id comes from path


class EditCaptionRequest(BaseModel):
    text: str = Field(min_length=1)
    author: str = "human"


class BulkCaptionRequest(BaseModel):
    asset_ids: list[str]
    provider: str
    style: str = "natural"
    options: dict | None = None


class BulkOperationRequest(BaseModel):
    asset_ids: list[str]
    operation: str  # "prepend" | "append" | "find_replace" | "normalize"
    text: str | None = None          # for prepend/append
    find: str | None = None          # for find_replace
    replace: str | None = None       # for find_replace
    use_regex: bool = False


class ConsistencyRequest(BaseModel):
    trigger_words: list[str] | None = None


class ExportSidecarsRequest(BaseModel):
    asset_ids: list[str] | None = None  # None = all
    output_dir: str | None = None


# ── Endpoints ─────────────────────────────────────────────────────────────────

@router.get("/assets/{asset_id}/captions", response_model=list[CaptionVersionResponse])
async def list_captions(
    asset_id: str,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> list[CaptionVersionResponse]:
    svc = get_caption_service()
    versions = await svc.list_versions(asset_id, db)
    return [CaptionVersionResponse.from_orm(v) for v in versions]


@router.post(
    "/assets/{asset_id}/captions/generate",
    response_model=CaptionVersionResponse,
    status_code=status.HTTP_201_CREATED,
)
async def generate_caption(
    asset_id: str,
    body: GenerateCaptionRequest,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> CaptionVersionResponse:
    svc = get_caption_service()
    try:
        version = await svc.generate(
            asset_id, body.provider, body.style, db, body.options, body.set_active
        )
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except (ValueError, RuntimeError) as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    await db.commit()
    return CaptionVersionResponse.from_orm(version)


@router.post(
    "/assets/{asset_id}/captions/compare",
    response_model=list[CaptionVersionResponse],
)
async def compare_providers(
    asset_id: str,
    body: CompareProvidersRequest,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> list[CaptionVersionResponse]:
    svc = get_caption_service()
    try:
        versions = await svc.compare_providers(
            asset_id, body.providers, body.style, db, body.options
        )
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except (ValueError, RuntimeError) as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    await db.commit()
    return [CaptionVersionResponse.from_orm(v) for v in versions]


@router.put("/captions/{version_id}/activate", response_model=dict)
async def activate_caption(
    version_id: str,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> dict:
    # Resolve asset_id from version
    from sqlalchemy import select
    from models.caption import CaptionVersion
    result = await db.execute(
        select(CaptionVersion).where(CaptionVersion.id == version_id)
    )
    version = result.scalar_one_or_none()
    if version is None:
        raise HTTPException(status_code=404, detail="Caption version not found")
    svc = get_caption_service()
    try:
        await svc.set_active(version.asset_id, version_id, db)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    await db.commit()
    return {"ok": True, "asset_id": version.asset_id, "version_id": version_id}


@router.post("/captions/{version_id}/edit", response_model=CaptionVersionResponse)
async def edit_caption(
    version_id: str,
    body: EditCaptionRequest,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> CaptionVersionResponse:
    svc = get_caption_service()
    try:
        new_version = await svc.edit(version_id, body.text, db, author=body.author)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    await db.commit()
    return CaptionVersionResponse.from_orm(new_version)


@router.delete("/captions/{version_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_caption(
    version_id: str,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> None:
    svc = get_caption_service()
    try:
        await svc.delete_version(version_id, db)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    await db.commit()


async def _validate_asset_ownership(project_id: str, asset_ids: list[str], db) -> list[str]:
    """Return only the asset IDs that belong to project_id; raise 422 if none match."""
    from sqlalchemy import select as _select
    from models.asset import Asset as _Asset
    result = await db.execute(
        _select(_Asset.id).where(
            _Asset.id.in_(asset_ids),
            _Asset.project_id == project_id,
        )
    )
    owned = [row[0] for row in result.all()]
    if not owned:
        raise HTTPException(status_code=422, detail="No requested assets belong to this project")
    return owned


@router.post("/projects/{project_id}/captions/bulk", status_code=status.HTTP_202_ACCEPTED)
async def bulk_caption_generate(
    project_id: str,
    body: BulkCaptionRequest,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> dict:
    owned_ids = await _validate_asset_ownership(project_id, body.asset_ids, db)
    svc = get_caption_service()
    job_id = await svc.generate_batch(
        owned_ids, body.provider, body.style, db, body.options
    )
    return {"job_id": job_id, "asset_count": len(owned_ids)}


@router.post("/projects/{project_id}/captions/bulk-edit")
async def bulk_edit_captions(
    project_id: str,
    body: BulkOperationRequest,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> dict:
    owned_ids = await _validate_asset_ownership(project_id, body.asset_ids, db)
    svc = get_caption_service()
    op = body.operation

    if op == "prepend":
        if not body.text:
            raise HTTPException(status_code=422, detail="'text' required for prepend")
        count = await svc.bulk_prepend(owned_ids, body.text, db)
    elif op == "append":
        if not body.text:
            raise HTTPException(status_code=422, detail="'text' required for append")
        count = await svc.bulk_append(owned_ids, body.text, db)
    elif op == "find_replace":
        if body.find is None or body.replace is None:
            raise HTTPException(status_code=422, detail="'find' and 'replace' required")
        count = await svc.bulk_find_replace(
            owned_ids, body.find, body.replace, db, body.use_regex
        )
    elif op == "normalize":
        count = await svc.normalize(owned_ids, db)
    else:
        raise HTTPException(status_code=422, detail=f"Unknown operation '{op}'")

    await db.commit()
    return {"operation": op, "modified": count}


@router.get("/projects/{project_id}/captions/export")
async def export_sidecars(
    project_id: str,
    db: Annotated[AsyncSession, Depends(get_db)],
    output_dir: str | None = Query(default=None),
) -> dict:
    from sqlalchemy import select
    from models.asset import Asset

    result = await db.execute(
        select(Asset.id).where(
            Asset.project_id == project_id,
            Asset.active_caption_id.isnot(None),
        )
    )
    asset_ids = [row[0] for row in result.all()]

    if not asset_ids:
        raise HTTPException(status_code=422, detail="No captioned assets to export")

    svc = get_caption_service()
    job_id = await svc.export_sidecars(project_id, asset_ids, db, output_dir)
    return {"job_id": job_id, "asset_count": len(asset_ids)}


@router.post("/projects/{project_id}/captions/export")
async def export_sidecars_post(
    project_id: str,
    body: ExportSidecarsRequest,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> dict:
    from sqlalchemy import select
    from models.asset import Asset

    if body.asset_ids:
        asset_ids = await _validate_asset_ownership(project_id, body.asset_ids, db)
    else:
        result = await db.execute(
            select(Asset.id).where(
                Asset.project_id == project_id,
                Asset.active_caption_id.isnot(None),
            )
        )
        asset_ids = [row[0] for row in result.all()]

    if not asset_ids:
        raise HTTPException(status_code=422, detail="No captioned assets to export")

    svc = get_caption_service()
    job_id = await svc.export_sidecars(project_id, asset_ids, db, body.output_dir)
    return {"job_id": job_id, "asset_count": len(asset_ids)}


@router.get("/projects/{project_id}/captions/consistency")
async def caption_consistency(
    project_id: str,
    db: Annotated[AsyncSession, Depends(get_db)],
    trigger_words: str | None = Query(default=None, description="Comma-separated trigger words"),
) -> dict:
    tw = [w.strip() for w in trigger_words.split(",")] if trigger_words else None
    svc = get_caption_service()
    report = await svc.analyze_consistency(project_id, db, trigger_words=tw)
    return {
        "total_captioned": report.total_captioned,
        "total_uncaptioned": report.total_uncaptioned,
        "avg_length": report.avg_length,
        "length_std": report.length_std,
        "common_words": [{"word": w, "count": c} for w, c in report.common_words],
        "rare_words": [{"word": w, "count": c} for w, c in report.rare_words],
        "trigger_word_presence": report.trigger_word_presence,
        "inconsistent_formatting": report.inconsistent_formatting,
        "recommendations": report.recommendations,
    }


# ── Legacy endpoint compat ────────────────────────────────────────────────────

@router.post("/assets/{asset_id}/captions", response_model=CaptionVersionResponse, status_code=status.HTTP_201_CREATED)
async def create_caption_legacy(
    asset_id: str,
    body: GenerateCaptionRequest,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> CaptionVersionResponse:
    """Legacy endpoint — prefer /generate."""
    return await generate_caption(asset_id, body, db)


@router.patch("/captions/{caption_id}", response_model=CaptionVersionResponse)
async def patch_caption_legacy(
    caption_id: str,
    body: EditCaptionRequest,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> CaptionVersionResponse:
    return await edit_caption(caption_id, body, db)


@router.post("/assets/{asset_id}/captions/{caption_id}/activate")
async def activate_by_asset_legacy(
    asset_id: str,
    caption_id: str,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> dict:
    svc = get_caption_service()
    try:
        await svc.set_active(asset_id, caption_id, db)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    await db.commit()
    return {"ok": True}


@router.post("/captions/bulk_prepend")
async def bulk_prepend(
    body: dict,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> dict:
    """Prepend text to captions for multiple assets."""
    asset_ids = body.get("asset_ids", [])
    prefix = body.get("prefix", "")
    if not prefix or not asset_ids:
        raise HTTPException(status_code=400, detail="prefix and asset_ids required")

    svc = get_caption_service()
    updated = await svc.bulk_prepend(asset_ids, prefix, db)
    await db.commit()
    return {"updated": updated}


@router.post("/captions/bulk_append")
async def bulk_append(
    body: dict,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> dict:
    """Append text to captions for multiple assets."""
    asset_ids = body.get("asset_ids", [])
    suffix = body.get("suffix", "")
    if not suffix or not asset_ids:
        raise HTTPException(status_code=400, detail="suffix and asset_ids required")

    svc = get_caption_service()
    updated = await svc.bulk_append(asset_ids, suffix, db)
    await db.commit()
    return {"updated": updated}


@router.post("/captions/bulk_replace")
async def bulk_replace(
    body: dict,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> dict:
    """Find and replace text in captions for multiple assets."""
    from sqlalchemy import select
    from models.asset import Asset

    asset_ids = body.get("asset_ids", [])
    find = body.get("find", "")
    replace_text = body.get("replace", "")
    project_id = body.get("project_id")

    if find is None:
        raise HTTPException(status_code=400, detail="find is required")

    if not asset_ids:
        if project_id:
            result = await db.execute(select(Asset.id).where(Asset.project_id == project_id))
            asset_ids = [row[0] for row in result.all()]
        else:
            raise HTTPException(status_code=400, detail="asset_ids or project_id required")

    svc = get_caption_service()
    updated = await svc.bulk_find_replace(asset_ids, find, replace_text, db)
    await db.commit()
    return {"updated": updated}


@router.get("/captions/consistency_check")
async def caption_consistency_check(
    project_id: str,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> dict:
    """Analyze caption consistency across the dataset."""
    svc = get_caption_service()
    report = await svc.analyze_consistency(project_id, db)
    total = report.total_captioned + report.total_uncaptioned
    return {
        "total": total,
        "captioned": report.total_captioned,
        "uncaptioned": report.total_uncaptioned,
        "coverage_pct": round(report.total_captioned / total * 100, 1) if total > 0 else 0,
        "avg_caption_length": round(report.avg_length),
        "top_words": [{"word": w, "count": c} for w, c in report.common_words],
        "inconsistent_formatting": len(report.inconsistent_formatting),
        "recommendations": report.recommendations,
    }


@router.post("/captions/bulk-generate", status_code=status.HTTP_202_ACCEPTED)
async def bulk_generate_legacy(
    body: BulkCaptionRequest,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> dict:
    svc = get_caption_service()
    job_id = await svc.generate_batch(
        body.asset_ids, body.provider, body.style, db, body.options
    )
    return {"job_id": job_id, "asset_count": len(body.asset_ids)}
