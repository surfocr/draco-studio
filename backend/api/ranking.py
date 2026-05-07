"""Ranking router — complete implementation."""
from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from database import get_db
from models.asset import Asset
from models.ranking import RankingSession
from services.ranking import get_ranking_service

router = APIRouter(prefix="/api", tags=["ranking"])


# ── Pydantic schemas ──────────────────────────────────────────────────────────

class CreateSessionRequest(BaseModel):
    name: str = "Ranking Session"
    engine: str = "openskill"   # "openskill" | "elo"
    scope: str = "all"          # "all" | "selected" | "custom"
    asset_ids: list[str] = Field(default_factory=list)
    strategy: str = "uncertainty"


class RecordComparisonRequest(BaseModel):
    winner_id: str
    loser_id: str
    draw: bool = False
    decided_by: str = "human"
    ai_explanation: str | None = None
    comparison_time_ms: int | None = None


class SkipPairRequest(BaseModel):
    asset_a_id: str
    asset_b_id: str


class AiCompareRequest(BaseModel):
    asset_id_a: str
    asset_id_b: str
    provider: str = "auto"


class SessionResponse(BaseModel):
    id: str
    project_id: str
    name: str
    ranking_algorithm: str
    asset_scope: str
    selection_strategy: str
    asset_ids_count: int
    skipped_pairs_count: int
    is_active: bool
    total_comparisons: int
    created_at: str

    model_config = {"from_attributes": True}


class LeaderboardEntry(BaseModel):
    asset_id: str
    filename: str
    rank: int
    mu: float
    sigma: float | None
    elo: float | None
    ordinal: float
    comparisons: int
    thumbnail_url: str | None = None


class AssetPairResponse(BaseModel):
    asset_a: dict
    asset_b: dict
    session_id: str


# ── Helpers ───────────────────────────────────────────────────────────────────

def _asset_to_dict(a: Asset, base_url: str = "") -> dict:
    return {
        "id": a.id,
        "filename": a.filename,
        "trueskill_mu": a.trueskill_mu,
        "trueskill_sigma": a.trueskill_sigma,
        "composite_score": a.composite_score,
        "face_count": a.face_count if hasattr(a, "face_count") else 0,
        "ranking_comparisons_count": a.ranking_comparisons_count or 0,
        "thumbnail_url": f"/api/assets/{a.id}/thumbnail?size=512",
    }


# ── Endpoints ─────────────────────────────────────────────────────────────────

@router.post(
    "/projects/{project_id}/ranking/sessions",
    response_model=SessionResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_session(
    project_id: str,
    body: CreateSessionRequest,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> SessionResponse:
    svc = get_ranking_service()

    # If no asset_ids provided, fetch all non-rejected assets
    asset_ids = body.asset_ids
    if body.scope in {"selected", "custom"} and not asset_ids:
        raise HTTPException(
            status_code=422,
            detail="asset_ids are required for selected/custom ranking sessions",
        )

    if not asset_ids:
        result = await db.execute(
            select(Asset.id).where(
                Asset.project_id == project_id,
                Asset.is_rejected.is_(False),
            )
        )
        asset_ids = [row[0] for row in result.all()]

    session = await svc.create_session(
        project_id, body.engine, body.scope, asset_ids, db,
        name=body.name, strategy=body.strategy,
    )
    await db.commit()

    return SessionResponse(
        id=session.id,
        project_id=session.project_id,
        name=session.name,
        ranking_algorithm=session.ranking_algorithm,
        asset_scope=session.asset_scope,
        selection_strategy=session.selection_strategy,
        asset_ids_count=len(session.asset_ids or []),
        skipped_pairs_count=len(session.skipped_pairs or []),
        is_active=session.is_active,
        total_comparisons=session.total_comparisons,
        created_at=session.created_at.isoformat(),
    )


@router.get("/projects/{project_id}/ranking/sessions", response_model=list[SessionResponse])
async def list_sessions(
    project_id: str,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> list[SessionResponse]:
    svc = get_ranking_service()
    sessions = await svc.list_sessions(project_id, db)
    return [
        SessionResponse(
            id=s.id,
            project_id=s.project_id,
            name=s.name,
            ranking_algorithm=s.ranking_algorithm,
            asset_scope=s.asset_scope,
            selection_strategy=s.selection_strategy,
            asset_ids_count=len(s.asset_ids or []),
            skipped_pairs_count=len(s.skipped_pairs or []),
            is_active=s.is_active,
            total_comparisons=s.total_comparisons,
            created_at=s.created_at.isoformat(),
        )
        for s in sessions
    ]


@router.get("/ranking/sessions/{session_id}")
async def get_session(
    session_id: str,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> dict:
    session = await db.get(RankingSession, session_id)
    if session is None:
        raise HTTPException(status_code=404, detail="Session not found")
    svc = get_ranking_service()
    leaderboard = await svc.get_leaderboard(session_id, db, limit=50)
    return {
        "id": session.id,
        "project_id": session.project_id,
        "name": session.name,
        "ranking_algorithm": session.ranking_algorithm,
        "asset_scope": session.asset_scope,
        "selection_strategy": session.selection_strategy,
        "asset_ids_count": len(session.asset_ids or []),
        "skipped_pairs_count": len(session.skipped_pairs or []),
        "is_active": session.is_active,
        "total_comparisons": session.total_comparisons,
        "created_at": session.created_at.isoformat(),
        "leaderboard": [
            {
                "asset_id": e.asset_id,
                "filename": e.filename,
                "rank": e.rank,
                "mu": e.mu,
                "sigma": e.sigma,
                "ordinal": e.ordinal,
                "comparisons": e.comparisons,
                "thumbnail_url": f"/api/assets/{e.asset_id}/thumbnail?size=128",
            }
            for e in leaderboard
        ],
    }


@router.get("/ranking/sessions/{session_id}/next-pair")
async def get_next_pair(
    session_id: str,
    db: Annotated[AsyncSession, Depends(get_db)],
    strategy: str | None = None,
) -> dict:
    svc = get_ranking_service()
    try:
        pair = await svc.get_next_pair(session_id, db, strategy=strategy)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc))

    if pair is None:
        return {"pair": None, "message": "Not enough assets to compare"}

    return {
        "asset_a": _asset_to_dict(pair[0]),
        "asset_b": _asset_to_dict(pair[1]),
        "session_id": session_id,
    }


@router.post("/ranking/sessions/{session_id}/compare")
async def record_comparison(
    session_id: str,
    body: RecordComparisonRequest,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> dict:
    svc = get_ranking_service()
    try:
        result = await svc.record_comparison(
            session_id,
            body.winner_id,
            body.loser_id,
            draw=body.draw,
            db=db,
            comparison_time_ms=body.comparison_time_ms,
            decided_by=body.decided_by,
            ai_explanation=body.ai_explanation,
        )
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    await db.commit()
    return {
        "winner": {
            "id": result.winner_id,
            "mu": result.winner_mu_after,
            "sigma": result.winner_sigma_after,
        },
        "loser": {
            "id": result.loser_id,
            "mu": result.loser_mu_after,
            "sigma": result.loser_sigma_after,
        },
        "is_draw": result.is_draw,
    }


@router.post("/ranking/sessions/{session_id}/skip")
async def skip_pair(
    session_id: str,
    body: SkipPairRequest,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> dict:
    svc = get_ranking_service()
    try:
        session = await svc.skip_pair(session_id, body.asset_a_id, body.asset_b_id, db)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    await db.commit()
    return {
        "session_id": session_id,
        "skipped_pairs_count": len(session.skipped_pairs or []),
    }


@router.post("/ranking/sessions/{session_id}/undo")
async def undo_last_comparison(
    session_id: str,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> dict:
    svc = get_ranking_service()
    try:
        result = await svc.revert_last_comparison(session_id, db)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    await db.commit()
    return {
        "session_id": result.session_id,
        "comparison_id": result.reverted_comparison_id,
        "winner_id": result.winner_id,
        "loser_id": result.loser_id,
        "total_comparisons": result.total_comparisons,
    }


@router.post("/ranking/sessions/{session_id}/apply")
async def apply_rankings(
    session_id: str,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> dict:
    svc = get_ranking_service()
    try:
        count = await svc.apply_to_assets(session_id, db)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    await db.commit()
    return {"assets_ranked": count, "session_id": session_id}


@router.get("/ranking/sessions/{session_id}/leaderboard", response_model=list[dict])
async def get_leaderboard(
    session_id: str,
    db: Annotated[AsyncSession, Depends(get_db)],
    limit: int = 100,
) -> list[dict]:
    svc = get_ranking_service()
    try:
        entries = await svc.get_leaderboard(session_id, db, limit=limit)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    return [
        {
            "asset_id": e.asset_id,
            "filename": e.filename,
            "rank": e.rank,
            "mu": e.mu,
            "sigma": e.sigma,
            "elo": e.elo,
            "ordinal": e.ordinal,
            "comparisons": e.comparisons,
            "thumbnail_url": f"/api/assets/{e.asset_id}/thumbnail?size=128",
        }
        for e in entries
    ]


@router.post("/assets/{asset_id}/ai-judge")
async def ai_judge_asset(
    asset_id: str,
    db: Annotated[AsyncSession, Depends(get_db)],
    provider: str = "auto",
) -> dict:
    svc = get_ranking_service()
    try:
        result = await svc.ai_judge_score(asset_id, db, provider_name=provider)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))

    return {
        "asset_id": result.asset_id,
        "composite": result.composite,
        "recommendation": result.recommendation,
        "confidence": result.confidence,
        "needs_human_review": result.needs_human_review,
        "review_reason": result.review_reason,
        "provider_used": result.provider_used,
        "is_fallback": result.is_fallback,
        "scores": {
            "technical_quality": {"score": result.technical_quality.score, "reason": result.technical_quality.reason},
            "aesthetic_quality": {"score": result.aesthetic_quality.score, "reason": result.aesthetic_quality.reason},
            "face_clarity": {"score": result.face_clarity.score, "reason": result.face_clarity.reason, "not_applicable": result.face_clarity.not_applicable},
            "pose_usefulness": {"score": result.pose_usefulness.score, "reason": result.pose_usefulness.reason},
            "expression_quality": {"score": result.expression_quality.score, "reason": result.expression_quality.reason},
            "background_usefulness": {"score": result.background_usefulness.score, "reason": result.background_usefulness.reason},
            "uniqueness": {"score": result.uniqueness.score, "reason": result.uniqueness.reason},
            "training_value": {"score": result.training_value.score, "reason": result.training_value.reason},
        },
        "strengths": result.strengths,
        "weaknesses": result.weaknesses,
    }


@router.post("/projects/{project_id}/ai-judge/batch", status_code=status.HTTP_202_ACCEPTED)
async def batch_ai_judge(
    project_id: str,
    db: Annotated[AsyncSession, Depends(get_db)],
    provider: str = "auto",
    asset_ids: list[str] | None = None,
) -> dict:
    if not asset_ids:
        result = await db.execute(
            select(Asset.id).where(Asset.project_id == project_id, Asset.is_rejected.is_(False))
        )
        asset_ids = [row[0] for row in result.all()]

    if not asset_ids:
        raise HTTPException(status_code=422, detail="No assets found for project")

    svc = get_ranking_service()
    job_id = await svc.ai_judge_batch(asset_ids, db, provider_name=provider)
    return {"job_id": job_id, "asset_count": len(asset_ids)}


@router.post("/ranking/sessions/{session_id}/ai-compare")
async def ai_compare_session_pair(
    session_id: str,
    body: AiCompareRequest,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> dict:
    svc = get_ranking_service()
    try:
        result = await svc.ai_judge_compare(
            body.asset_id_a, body.asset_id_b, db, provider_name=body.provider
        )
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))

    return {
        "winner": result.winner,
        "winner_asset_id": result.winner_asset_id,
        "confidence": result.confidence,
        "margin": result.margin,
        "overall_reasoning": result.overall_reasoning,
        "dimensions": {
            "technical_quality": result.technical_quality,
            "aesthetic_quality": result.aesthetic_quality,
            "face_clarity": result.face_clarity,
        },
        "a_strengths": result.a_strengths,
        "b_strengths": result.b_strengths,
        "dataset_contribution": result.dataset_contribution,
        "provider_used": result.provider_used,
    }


# ── Legacy endpoints (backward compat) ────────────────────────────────────────

@router.post("/ranking/sessions", status_code=status.HTTP_201_CREATED)
async def create_session_legacy(
    body: dict,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> dict:
    project_id = body.get("project_id", "")
    if not project_id:
        raise HTTPException(status_code=422, detail="project_id required")
    svc = get_ranking_service()
    session = await svc.create_session(
        project_id,
        engine=body.get("engine", "openskill"),
        scope="all",
        asset_ids=[],
        db=db,
        name=body.get("name", "Default Session"),
        strategy=body.get("strategy", "uncertainty"),
    )
    await db.commit()
    return {"id": session.id, "name": session.name}


@router.get("/ranking/sessions/{session_id}/next-pair-legacy")
async def get_next_pair_legacy(session_id: str, db: Annotated[AsyncSession, Depends(get_db)]) -> dict:
    return await get_next_pair(session_id, db)


@router.post("/ranking/sessions/{session_id}/rate")
async def submit_rating_legacy(
    session_id: str,
    body: dict,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> dict:
    req = RecordComparisonRequest(
        winner_id=body.get("winner_id", ""),
        loser_id=body.get("loser_id", ""),
        decided_by=body.get("decided_by", "human"),
        ai_explanation=body.get("ai_explanation"),
    )
    return await record_comparison(session_id, req, db)


@router.get("/projects/{project_id}/ranking/leaderboard")
async def leaderboard_legacy(
    project_id: str,
    db: Annotated[AsyncSession, Depends(get_db)],
    limit: int = 100,
) -> list[dict]:
    from services.ranking import get_leaderboard
    return await get_leaderboard(project_id, db, limit)


@router.get("/projects/{project_id}/ranking/next-pair")
async def next_pair_legacy(
    project_id: str,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> dict:
    result = await db.execute(
        select(RankingSession)
        .where(RankingSession.project_id == project_id, RankingSession.is_active.is_(True))
        .order_by(RankingSession.created_at.desc())
        .limit(1)
    )
    session = result.scalar_one_or_none()
    if session is None:
        return {"pair": None, "message": "No active session"}
    return await get_next_pair(session.id, db)


@router.post("/projects/{project_id}/ranking/rate")
async def rate_legacy(
    project_id: str,
    body: dict,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> dict:
    result = await db.execute(
        select(RankingSession)
        .where(RankingSession.project_id == project_id, RankingSession.is_active.is_(True))
        .order_by(RankingSession.created_at.desc())
        .limit(1)
    )
    session = result.scalar_one_or_none()
    if session is None:
        raise HTTPException(status_code=404, detail="No active session for project")
    req = RecordComparisonRequest(
        winner_id=body.get("winner_id", ""),
        loser_id=body.get("loser_id", ""),
        decided_by=body.get("decided_by", "human"),
    )
    return await record_comparison(session.id, req, db)
