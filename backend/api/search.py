"""Semantic search and smart filter API."""
from __future__ import annotations

from typing import List

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import and_, select
from sqlalchemy.ext.asyncio import AsyncSession

from config import settings
from database import get_db
from models.asset import Asset

router = APIRouter(prefix="/api/search", tags=["search"])


def _thumbnail_url(asset: Asset) -> str | None:
    """Return a browser-accessible URL for the asset thumbnail."""
    if asset.thumbnail_path:
        try:
            from pathlib import Path
            rel = Path(asset.thumbnail_path).relative_to(settings.storage_path)
            return f"/files/{rel.as_posix()}"
        except ValueError:
            pass
    return None


class TextSearchRequest(BaseModel):
    project_id: str
    query: str
    top_k: int = 20
    min_similarity: float = 0.3


class SmartFilterRequest(BaseModel):
    project_id: str
    rules: List[dict]  # e.g. [{"field": "composite_score", "op": "lt", "value": 0.4}]
    limit: int = 200


@router.post("/text")
async def text_to_image_search(
    req: TextSearchRequest, db: AsyncSession = Depends(get_db)
):
    """Find images semantically similar to a text query using FastEmbed + Qdrant."""
    try:
        from providers.registry import get_registry

        embed_provider = get_registry().get("embedding", "fastembed")
        if not embed_provider:
            raise HTTPException(status_code=503, detail="Embedding provider not available")

        text_vector = await embed_provider.embed_text(req.query)

        hits = await embed_provider.search_similar(
            vector=text_vector,
            top_k=req.top_k,
            threshold=req.min_similarity,
            filter_project_id=req.project_id,
        )

        if not hits:
            return {"results": [], "query": req.query}

        asset_ids = [asset_id for asset_id, _ in hits]
        scores = {asset_id: score for asset_id, score in hits}

        result = await db.execute(select(Asset).where(Asset.id.in_(asset_ids)))
        assets = result.scalars().all()
        assets_sorted = sorted(assets, key=lambda a: scores.get(a.id, 0), reverse=True)

        return {
            "results": [
                {
                    "id": a.id,
                    "filename": a.filename,
                    "thumbnail_url": _thumbnail_url(a),
                    "composite_score": a.composite_score,
                    "similarity": scores.get(a.id, 0),
                    "caption_text": None,
                }
                for a in assets_sorted
            ],
            "query": req.query,
        }
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/similar_image")
async def image_to_image_search(
    project_id: str,
    asset_id: str,
    top_k: int = 20,
    db: AsyncSession = Depends(get_db),
):
    """Find images visually similar to a given asset using CLIP embeddings."""
    try:
        asset = await db.get(Asset, asset_id)
        if not asset:
            raise HTTPException(status_code=404, detail="Asset not found")

        from providers.registry import get_registry

        embed_provider = get_registry().get("embedding", "fastembed")
        if not embed_provider:
            raise HTTPException(status_code=503, detail="Embedding provider not available")

        embed_result = await embed_provider.embed_image(asset.filepath)

        hits = await embed_provider.search_similar(
            vector=embed_result.vector,
            top_k=top_k + 1,
            filter_project_id=project_id,
        )
        # Exclude the query asset itself
        hits = [(aid, score) for aid, score in hits if aid != asset_id][:top_k]

        result_ids = [aid for aid, _ in hits]
        scores = {aid: score for aid, score in hits}

        assets_result = await db.execute(select(Asset).where(Asset.id.in_(result_ids)))
        assets = assets_result.scalars().all()
        assets_sorted = sorted(assets, key=lambda a: scores.get(a.id, 0), reverse=True)

        return {
            "results": [
                {
                    "id": a.id,
                    "filename": a.filename,
                    "thumbnail_url": _thumbnail_url(a),
                    "composite_score": a.composite_score,
                    "similarity": scores.get(a.id, 0),
                }
                for a in assets_sorted
            ],
            "source_asset_id": asset_id,
        }
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/smart_filter")
async def smart_filter(req: SmartFilterRequest, db: AsyncSession = Depends(get_db)):
    """Apply a rules-based filter to return matching assets."""
    query = select(Asset).where(Asset.project_id == req.project_id)

    FIELD_MAP = {
        "composite_score": Asset.composite_score,
        "face_count": Asset.face_count,
        "aesthetic_score": Asset.aesthetic_score,
        "technical_quality": Asset.technical_quality,
        "review_state": Asset.review_state,
        "shot_type": Asset.shot_type,
        "dominant_emotion": Asset.dominant_emotion,
        "is_augmented": Asset.is_augmented,
        "active_caption_id": Asset.active_caption_id,
    }

    conditions = []
    for rule in req.rules:
        field = rule.get("field")
        op = rule.get("op")
        val = rule.get("value")
        col = FIELD_MAP.get(field)
        if col is None:
            continue
        if op == "lt":
            conditions.append(col < val)
        elif op == "lte":
            conditions.append(col <= val)
        elif op == "gt":
            conditions.append(col > val)
        elif op == "gte":
            conditions.append(col >= val)
        elif op == "eq":
            conditions.append(col == val)
        elif op == "neq":
            conditions.append(col != val)
        elif op == "is_null":
            conditions.append(col.is_(None))
        elif op == "is_not_null":
            conditions.append(col.isnot(None))
        elif op == "contains":
            conditions.append(col.ilike(f"%{val}%"))

    if conditions:
        query = query.where(and_(*conditions))

    query = query.limit(req.limit)
    result = await db.execute(query)
    assets = result.scalars().all()
    return [
        {
            "id": a.id,
            "filename": a.filename,
            "thumbnail_url": a.thumbnail_path,
            "composite_score": a.composite_score,
            "review_state": a.review_state,
        }
        for a in assets
    ]
