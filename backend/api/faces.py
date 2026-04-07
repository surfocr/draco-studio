"""Faces and identity cluster router."""
from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from database import get_db
from models.asset import Asset
from models.face import FaceCluster, IdentityCluster

router = APIRouter(prefix="/api", tags=["faces"])


@router.get("/projects/{project_id}/identities")
async def list_identities(
    project_id: str,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> list[dict]:
    result = await db.execute(
        select(IdentityCluster)
        .where(IdentityCluster.project_id == project_id)
        .order_by(IdentityCluster.asset_count.desc())
    )
    clusters = result.scalars().all()
    return [
        {
            "id": c.id,
            "label": c.label,
            "is_subject": c.is_subject,
            "asset_count": c.asset_count,
            "thumbnail_asset_id": c.thumbnail_asset_id,
            "mean_age_estimate": c.mean_age_estimate,
            "dominant_gender": c.dominant_gender,
        }
        for c in clusters
    ]


@router.patch("/identities/{cluster_id}")
async def update_identity(
    cluster_id: str,
    db: Annotated[AsyncSession, Depends(get_db)],
    label: str | None = None,
    is_subject: bool | None = None,
) -> dict:
    cluster = await db.get(IdentityCluster, cluster_id)
    if not cluster:
        raise HTTPException(status_code=404, detail="Identity cluster not found")
    if label is not None:
        cluster.label = label
    if is_subject is not None:
        cluster.is_subject = is_subject
    await db.flush()
    return {"ok": True, "id": cluster_id, "label": cluster.label}


@router.get("/faces/clusters")
async def list_face_clusters(
    project_id: str,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> list[dict]:
    """List identity clusters with face counts and thumbnail URLs."""
    result = await db.execute(
        select(IdentityCluster)
        .where(IdentityCluster.project_id == project_id)
        .order_by(IdentityCluster.asset_count.desc())
    )
    clusters = result.scalars().all()

    out = []
    for c in clusters:
        thumbnail_url = (
            f"/api/assets/{c.thumbnail_asset_id}/thumbnail"
            if c.thumbnail_asset_id
            else None
        )
        # Collect asset_ids for this cluster
        assets_result = await db.execute(
            select(Asset.id).where(Asset.identity_cluster_id == c.id)
        )
        asset_ids = [str(row[0]) for row in assets_result.all()]
        out.append({
            "id": c.id,
            "label": c.label,
            "face_count": c.asset_count,
            "asset_ids": asset_ids,
            "thumbnail_url": thumbnail_url,
        })
    return out


@router.get("/faces/clusters/{cluster_id}/assets")
async def list_cluster_assets(
    cluster_id: str,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> list[dict]:
    """Return assets belonging to the given identity cluster."""
    result = await db.execute(
        select(Asset).where(Asset.identity_cluster_id == cluster_id)
    )
    assets = result.scalars().all()
    return [
        {
            "id": str(a.id),
            "filename": a.filename,
            "thumbnail_url": f"/api/assets/{a.id}/thumbnail",
            "composite_score": a.composite_score,
        }
        for a in assets
    ]


@router.post("/faces/clusters/{cluster_id}/rename")
async def rename_cluster(
    cluster_id: str,
    body: dict,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> dict:
    cluster = await db.get(IdentityCluster, cluster_id)
    if not cluster:
        raise HTTPException(status_code=404, detail="Cluster not found")
    cluster.label = body.get("label", cluster.label)
    await db.flush()
    return {"ok": True, "id": cluster_id, "label": cluster.label}


@router.post("/faces/clusters/merge")
async def merge_clusters(
    body: dict,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> dict:
    """Merge source cluster into target: reassign all assets, then delete source."""
    source_id = body["source_id"]
    target_id = body["target_id"]

    # Reassign all assets from source to target
    await db.execute(
        update(Asset)
        .where(Asset.identity_cluster_id == source_id)
        .values(identity_cluster_id=target_id)
    )

    # Update target asset count
    count_result = await db.execute(
        select(Asset.id).where(Asset.identity_cluster_id == target_id)
    )
    new_count = len(count_result.all())
    target = await db.get(IdentityCluster, target_id)
    if target:
        target.asset_count = new_count

    # Delete source cluster
    source = await db.get(IdentityCluster, source_id)
    if source:
        await db.delete(source)

    await db.commit()
    return {"merged": True, "target_id": target_id, "new_face_count": new_count}


@router.post("/projects/{project_id}/faces/cluster")
async def run_face_clustering_endpoint(
    project_id: str,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> dict:
    """Trigger agglomerative face clustering for the project. Returns job_id."""
    from workers.job_queue import get_job_queue
    from database import AsyncSessionLocal

    async def _cluster() -> dict:
        from services.face_clustering import run_face_clustering
        async with AsyncSessionLocal() as session:
            return await run_face_clustering(project_id, session)

    queue = get_job_queue()
    job_id = await queue.submit(_cluster, job_type="face_clustering")
    return {"job_id": job_id}
