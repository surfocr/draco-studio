"""
Ranking service — full implementation with OpenSkill and Elo engines.
Manages ranking sessions, pairwise comparisons, leaderboards, and AI judge integration.
"""
from __future__ import annotations

import logging
import random
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from models.asset import Asset
from models.ranking import RankingComparison, RankingSession

logger = logging.getLogger(__name__)

_INITIAL_MU = 25.0
_INITIAL_SIGMA = 25.0 / 3.0


@dataclass
class ComparisonResult:
    session_id: str
    winner_id: str
    loser_id: str
    is_draw: bool
    winner_mu_after: float
    loser_mu_after: float
    winner_sigma_after: float | None
    loser_sigma_after: float | None


@dataclass
class RankingEntry:
    asset_id: str
    filename: str
    rank: int
    mu: float
    sigma: float | None
    elo: float | None
    ordinal: float
    comparisons: int
    ai_composite: float | None = None
    thumbnail_path: str | None = None


class RankingService:
    """Full ranking workflow: sessions, comparisons, leaderboards, AI judging."""

    # ── Session management ────────────────────────────────────────────────────

    async def create_session(
        self,
        project_id: str,
        engine: str,
        scope: str,
        asset_ids: list[str],
        db: AsyncSession,
        name: str = "Ranking Session",
        strategy: str = "uncertainty",
    ) -> RankingSession:
        session = RankingSession(
            id=str(uuid.uuid4()),
            project_id=project_id,
            name=name,
            ranking_algorithm=engine,
        )
        db.add(session)
        await db.flush()
        logger.info(
            "Created ranking session %s for %d assets (engine=%s, scope=%s)",
            session.id[:8], len(asset_ids), engine, scope,
        )
        return session

    async def list_sessions(self, project_id: str, db: AsyncSession) -> list[RankingSession]:
        result = await db.execute(
            select(RankingSession)
            .where(RankingSession.project_id == project_id)
            .order_by(RankingSession.created_at.desc())
        )
        return list(result.scalars().all())

    # ── Comparisons ───────────────────────────────────────────────────────────

    async def record_comparison(
        self,
        session_id: str,
        winner_id: str,
        loser_id: str,
        draw: bool,
        db: AsyncSession,
        comparison_time_ms: int | None = None,
        decided_by: str = "human",
        ai_explanation: str | None = None,
    ) -> ComparisonResult:
        session = await db.get(RankingSession, session_id)
        if session is None:
            raise LookupError(f"Session {session_id} not found")

        winner = await db.get(Asset, winner_id)
        loser = await db.get(Asset, loser_id)
        if not winner or not loser:
            raise LookupError("One or both assets not found")

        engine = session.ranking_algorithm or "openskill"
        winner_mu_before = winner.trueskill_mu
        loser_mu_before = loser.trueskill_mu

        if engine == "openskill":
            w_mu, w_sigma, l_mu, l_sigma = self._apply_openskill(
                winner_id, winner.trueskill_mu, winner.trueskill_sigma,
                loser_id, loser.trueskill_mu, loser.trueskill_sigma,
                draw=draw,
            )
            winner.trueskill_mu = w_mu
            winner.trueskill_sigma = w_sigma
            loser.trueskill_mu = l_mu
            loser.trueskill_sigma = l_sigma
            result_sigma_w: float | None = w_sigma
            result_sigma_l: float | None = l_sigma
        else:
            w_elo, l_elo = self._apply_elo(winner.elo_rating, loser.elo_rating, draw=draw)
            winner.elo_rating = w_elo
            loser.elo_rating = l_elo
            winner.trueskill_mu = w_elo / 60.0
            loser.trueskill_mu = l_elo / 60.0
            result_sigma_w = None
            result_sigma_l = None

        winner.ranking_comparisons_count = (winner.ranking_comparisons_count or 0) + 1
        loser.ranking_comparisons_count = (loser.ranking_comparisons_count or 0) + 1

        comparison = RankingComparison(
            id=str(uuid.uuid4()),
            session_id=session_id,
            project_id=session.project_id,
            winner_asset_id=winner_id,
            loser_asset_id=loser_id,
            winner_mu_before=winner_mu_before,
            winner_mu_after=winner.trueskill_mu,
            loser_mu_before=loser_mu_before,
            loser_mu_after=loser.trueskill_mu,
            ai_explanation=ai_explanation,
            decided_by=decided_by,
            latency_ms=comparison_time_ms,
        )
        db.add(comparison)
        session.total_comparisons = (session.total_comparisons or 0) + 1
        await db.flush()

        return ComparisonResult(
            session_id=session_id,
            winner_id=winner_id,
            loser_id=loser_id,
            is_draw=draw,
            winner_mu_after=winner.trueskill_mu,
            loser_mu_after=loser.trueskill_mu,
            winner_sigma_after=result_sigma_w,
            loser_sigma_after=result_sigma_l,
        )

    def _apply_openskill(
        self,
        winner_id: str, w_mu: float, w_sigma: float,
        loser_id: str, l_mu: float, l_sigma: float,
        draw: bool = False,
    ) -> tuple[float, float, float, float]:
        try:
            from providers.ranking.openskill_engine import OpenSkillRankingEngine
            engine = OpenSkillRankingEngine()
            engine.import_ratings([
                {"asset_id": winner_id, "mu": w_mu, "sigma": w_sigma},
                {"asset_id": loser_id, "mu": l_mu, "sigma": l_sigma},
            ])
            if draw:
                w_r, l_r = engine.rate_draw(winner_id, loser_id)
            else:
                w_r, l_r = engine.rate_pair(winner_id, loser_id)
            return w_r.mu, w_r.sigma, l_r.mu, l_r.sigma
        except Exception as exc:
            logger.warning("OpenSkill rating failed: %s — using Elo fallback", exc)
            w_elo, l_elo = self._apply_elo(w_mu * 60, l_mu * 60, draw)
            return w_elo / 60, w_sigma * 0.99, l_elo / 60, l_sigma * 0.99

    def _apply_elo(
        self, winner_elo: float, loser_elo: float, draw: bool = False
    ) -> tuple[float, float]:
        K = 32
        expected_w = 1.0 / (1.0 + 10 ** ((loser_elo - winner_elo) / 400.0))
        if draw:
            new_w = winner_elo + K * (0.5 - expected_w)
            new_l = loser_elo + K * (0.5 - (1.0 - expected_w))
        else:
            new_w = winner_elo + K * (1.0 - expected_w)
            new_l = loser_elo + K * (0.0 - (1.0 - expected_w))
        return new_w, new_l

    # ── Next pair selection ───────────────────────────────────────────────────

    async def get_next_pair(
        self,
        session_id: str,
        db: AsyncSession,
        strategy: str = "uncertainty",
    ) -> tuple[Asset, Asset] | None:
        session = await db.get(RankingSession, session_id)
        if session is None:
            raise LookupError(f"Session {session_id} not found")

        if strategy == "uncertainty":
            result = await db.execute(
                select(Asset)
                .where(Asset.project_id == session.project_id, Asset.is_rejected.is_(False))
                .order_by(Asset.trueskill_sigma.desc())
                .limit(20)
            )
        else:
            result = await db.execute(
                select(Asset)
                .where(Asset.project_id == session.project_id, Asset.is_rejected.is_(False))
                .limit(100)
            )

        candidates = list(result.scalars().all())
        if len(candidates) < 2:
            return None

        if strategy == "uncertainty" and len(candidates) >= 2:
            a, b = candidates[0], candidates[1]
            if len(candidates) >= 4 and random.random() < 0.25:
                b = candidates[random.randint(2, min(len(candidates) - 1, 9))]
            return a, b

        pair = random.sample(candidates, 2)
        return pair[0], pair[1]

    # ── Leaderboard ───────────────────────────────────────────────────────────

    async def get_leaderboard(
        self,
        session_id: str,
        db: AsyncSession,
        limit: int = 100,
    ) -> list[RankingEntry]:
        session = await db.get(RankingSession, session_id)
        if session is None:
            raise LookupError(f"Session {session_id} not found")

        result = await db.execute(
            select(Asset)
            .where(Asset.project_id == session.project_id)
            .order_by((Asset.trueskill_mu - Asset.trueskill_sigma * 3).desc())
            .limit(limit)
        )
        assets = list(result.scalars().all())

        return [
            RankingEntry(
                asset_id=a.id,
                filename=a.filename,
                rank=idx + 1,
                mu=a.trueskill_mu,
                sigma=a.trueskill_sigma,
                elo=getattr(a, "elo_rating", None),
                ordinal=a.trueskill_mu - 3 * a.trueskill_sigma,
                comparisons=a.ranking_comparisons_count or 0,
                thumbnail_path=getattr(a, "thumbnail_path", None),
            )
            for idx, a in enumerate(assets)
        ]

    async def apply_to_assets(self, session_id: str, db: AsyncSession) -> int:
        """Rankings live on Asset model already — mark session complete."""
        session = await db.get(RankingSession, session_id)
        if session is None:
            raise LookupError(f"Session {session_id} not found")
        result = await db.execute(
            select(Asset).where(
                Asset.project_id == session.project_id,
                Asset.ranking_comparisons_count > 0,
            )
        )
        count = len(result.scalars().all())
        session.is_active = False
        await db.flush()
        return count

    # ── AI judge ──────────────────────────────────────────────────────────────

    async def ai_judge_score(
        self,
        asset_id: str,
        db: AsyncSession,
        provider_name: str = "auto",
    ) -> Any:
        from services.ai_judge import get_ai_judge
        asset = await db.get(Asset, asset_id)
        if asset is None:
            raise LookupError(f"Asset {asset_id} not found")

        analysis = {
            "technical_quality": asset.technical_quality,
            "aesthetic_score": asset.aesthetic_score,
            "face_quality": asset.face_quality,
            "training_usefulness": asset.training_usefulness,
            "composite_score": asset.composite_score,
        }

        judge = get_ai_judge(provider_name)
        return await judge.score_image(asset.filepath, asset_id, existing_analysis=analysis)

    async def ai_judge_compare(
        self,
        asset_id_a: str,
        asset_id_b: str,
        db: AsyncSession,
        provider_name: str = "auto",
    ) -> Any:
        from services.ai_judge import get_ai_judge
        asset_a = await db.get(Asset, asset_id_a)
        asset_b = await db.get(Asset, asset_id_b)
        if not asset_a or not asset_b:
            raise LookupError("One or both assets not found")

        judge = get_ai_judge(provider_name)
        return await judge.compare_images(
            asset_a.filepath, asset_id_a,
            asset_b.filepath, asset_id_b,
        )

    async def ai_judge_batch(
        self,
        asset_ids: list[str],
        db: AsyncSession,
        provider_name: str = "auto",
    ) -> str:
        from workers.tasks import queue_ai_judge_task
        job_id = str(uuid.uuid4())
        await queue_ai_judge_task(asset_ids, provider_name, job_id=job_id)
        return job_id


# ── Singleton ─────────────────────────────────────────────────────────────────

_ranking_service: RankingService | None = None


def get_ranking_service() -> RankingService:
    global _ranking_service
    if _ranking_service is None:
        _ranking_service = RankingService()
    return _ranking_service


# ── Legacy helpers (backward compat) ──────────────────────────────────────────

async def rate_pair(
    winner_id: str,
    loser_id: str,
    session_id: str,
    db: AsyncSession,
    decided_by: str = "human",
    ai_explanation: str | None = None,
) -> tuple[Asset | None, Asset | None]:
    svc = get_ranking_service()
    try:
        result = await svc.record_comparison(
            session_id, winner_id, loser_id, draw=False, db=db,
            decided_by=decided_by, ai_explanation=ai_explanation,
        )
        winner = await db.get(Asset, result.winner_id)
        loser = await db.get(Asset, result.loser_id)
        return winner, loser
    except Exception as exc:
        logger.error("rate_pair: %s", exc)
        return None, None


async def select_next_pair(
    project_id: str, db: AsyncSession
) -> tuple[str, str] | None:
    result = await db.execute(
        select(RankingSession)
        .where(RankingSession.project_id == project_id, RankingSession.is_active.is_(True))
        .limit(1)
    )
    session = result.scalar_one_or_none()
    if session is None:
        return None
    svc = get_ranking_service()
    pair = await svc.get_next_pair(session.id, db)
    if pair is None:
        return None
    return pair[0].id, pair[1].id


async def get_leaderboard(
    project_id: str, db: AsyncSession, limit: int = 100
) -> list[dict]:
    result = await db.execute(
        select(Asset)
        .where(Asset.project_id == project_id, Asset.ranking_comparisons_count > 0)
        .order_by((Asset.trueskill_mu - Asset.trueskill_sigma * 3).desc())
        .limit(limit)
    )
    assets = result.scalars().all()
    return [
        {
            "id": a.id,
            "filename": a.filename,
            "mu": a.trueskill_mu,
            "sigma": a.trueskill_sigma,
            "ordinal": a.trueskill_mu - 3 * a.trueskill_sigma,
            "comparisons": a.ranking_comparisons_count or 0,
        }
        for a in assets
    ]
