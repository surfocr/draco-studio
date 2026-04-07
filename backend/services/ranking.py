"""
Ranking service — full implementation with OpenSkill and Elo engines.
Manages ranking sessions, pairwise comparisons, leaderboards, and AI judge integration.
"""
from __future__ import annotations

import logging
import random
import uuid
from collections.abc import Iterable
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
_PAIR_POOL_LIMIT = 72


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
class RevertResult:
    session_id: str
    reverted_comparison_id: str
    winner_id: str
    loser_id: str
    total_comparisons: int


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
        normalized_scope = (scope or "all").lower()
        normalized_strategy = (strategy or "uncertainty").lower()
        asset_id_list = list(asset_ids or [])
        if not asset_id_list:
            result = await db.execute(
                select(Asset.id).where(
                    Asset.project_id == project_id,
                    Asset.is_rejected.is_(False),
                )
            )
            asset_id_list = [row[0] for row in result.all()]
        session = RankingSession(
            id=str(uuid.uuid4()),
            project_id=project_id,
            name=name,
            ranking_algorithm=engine,
            asset_scope=normalized_scope,
            selection_strategy=normalized_strategy,
            asset_ids=asset_id_list,
            initial_asset_ratings=await self._build_initial_asset_ratings(asset_id_list, db),
            skipped_pairs=[],
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

        # Validate both assets belong to the session's project
        if winner.project_id != session.project_id or loser.project_id != session.project_id:
            raise ValueError("Both assets must belong to the session's project")

        # If session is scoped to specific assets, enforce membership
        if session.asset_ids:
            scope = set(session.asset_ids)
            if winner_id not in scope or loser_id not in scope:
                raise ValueError("Both assets must be within the session's asset scope")

        engine = session.ranking_algorithm or "openskill"
        # Snapshot all rating fields before mutation (for clean undo)
        winner_mu_before = winner.trueskill_mu
        winner_sigma_before = winner.trueskill_sigma
        winner_elo_before = winner.elo_rating
        loser_mu_before = loser.trueskill_mu
        loser_sigma_before = loser.trueskill_sigma
        loser_elo_before = loser.elo_rating

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
            winner_sigma_before=winner_sigma_before,
            loser_sigma_before=loser_sigma_before,
            winner_elo_before=winner_elo_before,
            loser_elo_before=loser_elo_before,
            ai_explanation=ai_explanation,
            is_draw=draw,
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
        strategy: str | None = "uncertainty",
    ) -> tuple[Asset, Asset] | None:
        session = await db.get(RankingSession, session_id)
        if session is None:
            raise LookupError(f"Session {session_id} not found")

        active_strategy = (strategy or session.selection_strategy or "uncertainty").lower()
        assets = await self._load_session_assets(session, db)
        if len(assets) < 2:
            return None

        compared_pairs = await self._load_compared_pairs(session, db)

        if active_strategy == "random":
            return self._pick_random_uncompared_pair(assets, compared_pairs)

        pool = self._select_candidate_pool(assets, strategy=active_strategy)
        pair = self._pick_smart_pair(pool, compared_pairs, strategy=active_strategy)
        if pair is not None:
            return pair

        if pool != assets:
            pair = self._pick_smart_pair(assets, compared_pairs, strategy=active_strategy)
            if pair is not None:
                return pair

        return self._pick_random_uncompared_pair(assets, compared_pairs)

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

        stmt = select(Asset).where(Asset.project_id == session.project_id)
        # If session is scoped to specific assets, filter to those only
        if session.asset_ids:
            stmt = stmt.where(Asset.id.in_(session.asset_ids))
        stmt = stmt.order_by(
            (Asset.trueskill_mu - Asset.trueskill_sigma * 3).desc()
        ).limit(limit)
        result = await db.execute(stmt)
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

        judge = get_ai_judge(
            provider_name,
            project_id=asset.project_id,
            task_key="ranking_explanation",
        )
        return await judge.score_image(
            asset.filepath,
            asset_id,
            db=db,
            existing_analysis=analysis,
        )

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

        judge = get_ai_judge(
            provider_name,
            project_id=asset_a.project_id,
            task_key="ranking_explanation",
        )
        return await judge.compare_images(
            asset_a.filepath, asset_id_a,
            asset_b.filepath, asset_id_b,
            db=db,
        )

    async def ai_judge_batch(
        self,
        asset_ids: list[str],
        db: AsyncSession,
        provider_name: str = "auto",
    ) -> str:
        from workers.tasks import queue_ai_judge_task
        return await queue_ai_judge_task(asset_ids, provider_name)

    async def skip_pair(
        self,
        session_id: str,
        asset_a_id: str,
        asset_b_id: str,
        db: AsyncSession,
    ) -> RankingSession:
        session = await db.get(RankingSession, session_id)
        if session is None:
            raise LookupError(f"Session {session_id} not found")

        asset_ids = set(session.asset_ids or [])
        if asset_a_id not in asset_ids or asset_b_id not in asset_ids:
            raise LookupError("Skip pair must belong to the ranking session scope")

        canonical = list(self._canonical_pair(asset_a_id, asset_b_id))
        skipped_pairs = list(session.skipped_pairs or [])
        if canonical not in skipped_pairs:
            skipped_pairs.append(canonical)
            session.skipped_pairs = skipped_pairs
            await db.flush()
        return session

    async def revert_last_comparison(
        self,
        session_id: str,
        db: AsyncSession,
    ) -> RevertResult:
        session = await db.get(RankingSession, session_id)
        if session is None:
            raise LookupError(f"Session {session_id} not found")

        result = await db.execute(
            select(RankingComparison)
            .where(RankingComparison.session_id == session_id)
            .order_by(RankingComparison.created_at.desc(), RankingComparison.id.desc())
            .limit(1)
        )
        comparison = result.scalar_one_or_none()
        if comparison is None:
            raise LookupError("No comparisons available to revert")

        # Cross-session guard: reject undo if either asset was compared in
        # another session AFTER this comparison was recorded. This prevents
        # overwriting ratings written by a different session.
        affected_ids = [comparison.winner_asset_id, comparison.loser_asset_id]
        later_result = await db.execute(
            select(RankingComparison.id).where(
                RankingComparison.session_id != session_id,
                (RankingComparison.winner_asset_id.in_(affected_ids))
                | (RankingComparison.loser_asset_id.in_(affected_ids)),
                RankingComparison.created_at > comparison.created_at,
            ).limit(1)
        )
        if later_result.scalar_one_or_none() is not None:
            raise ValueError(
                "Cannot undo: these assets have been compared in another session since this comparison. "
                "Undoing would corrupt those later ratings."
            )

        # Delta-based undo: restore ALL before-values stored on the comparison.
        winner = await db.get(Asset, comparison.winner_asset_id)
        loser = await db.get(Asset, comparison.loser_asset_id)
        if winner is not None:
            winner.trueskill_mu = float(comparison.winner_mu_before)
            if comparison.winner_sigma_before is not None:
                winner.trueskill_sigma = float(comparison.winner_sigma_before)
            if comparison.winner_elo_before is not None:
                winner.elo_rating = float(comparison.winner_elo_before)
            winner.ranking_comparisons_count = max(
                (winner.ranking_comparisons_count or 1) - 1, 0
            )
        if loser is not None:
            loser.trueskill_mu = float(comparison.loser_mu_before)
            if comparison.loser_sigma_before is not None:
                loser.trueskill_sigma = float(comparison.loser_sigma_before)
            if comparison.loser_elo_before is not None:
                loser.elo_rating = float(comparison.loser_elo_before)
            loser.ranking_comparisons_count = max(
                (loser.ranking_comparisons_count or 1) - 1, 0
            )

        reverted = RevertResult(
            session_id=session_id,
            reverted_comparison_id=comparison.id,
            winner_id=comparison.winner_asset_id,
            loser_id=comparison.loser_asset_id,
            total_comparisons=max((session.total_comparisons or 0) - 1, 0),
        )
        await db.delete(comparison)
        session.total_comparisons = reverted.total_comparisons
        await db.flush()
        return reverted

    async def _build_initial_asset_ratings(
        self,
        asset_ids: list[str],
        db: AsyncSession,
    ) -> dict[str, dict[str, float | int]]:
        if not asset_ids:
            return {}
        result = await db.execute(select(Asset).where(Asset.id.in_(asset_ids)))
        assets = list(result.scalars().all())
        return {
            asset.id: {
                "trueskill_mu": float(asset.trueskill_mu),
                "trueskill_sigma": float(asset.trueskill_sigma),
                "elo_rating": float(asset.elo_rating),
                "ranking_comparisons_count": int(asset.ranking_comparisons_count or 0),
            }
            for asset in assets
        }

    async def _load_session_assets(
        self,
        session: RankingSession,
        db: AsyncSession,
    ) -> list[Asset]:
        stmt = select(Asset).where(
            Asset.project_id == session.project_id,
            Asset.is_rejected.is_(False),
        )

        if session.asset_ids:
            stmt = stmt.where(Asset.id.in_(session.asset_ids))

        result = await db.execute(stmt)
        assets = list(result.scalars().all())
        return [asset for asset in assets if not asset.is_rejected]

    async def _load_compared_pairs(
        self,
        session: RankingSession,
        db: AsyncSession,
    ) -> set[tuple[str, str]]:
        result = await db.execute(
            select(
                RankingComparison.winner_asset_id,
                RankingComparison.loser_asset_id,
            ).where(RankingComparison.session_id == session.id)
        )
        compared = {
            self._canonical_pair(winner_id, loser_id)
            for winner_id, loser_id in result.all()
        }
        compared.update(
            self._canonical_pair(pair[0], pair[1])
            for pair in (session.skipped_pairs or [])
            if isinstance(pair, list) and len(pair) == 2
        )
        return compared

    def _select_candidate_pool(
        self,
        assets: list[Asset],
        *,
        strategy: str,
        pool_limit: int = _PAIR_POOL_LIMIT,
    ) -> list[Asset]:
        if len(assets) <= pool_limit:
            return assets

        quality_sorted = sorted(assets, key=self._quality_priority, reverse=True)
        uncertainty_sorted = sorted(
            assets,
            key=lambda asset: (
                float(asset.trueskill_sigma or 0.0),
                self._quality_priority(asset),
            ),
            reverse=True,
        )
        least_compared_sorted = sorted(
            assets,
            key=lambda asset: (
                int(asset.ranking_comparisons_count or 0),
                -self._quality_priority(asset),
                -float(asset.trueskill_sigma or 0.0),
            ),
        )

        ordered_groups: list[Iterable[Asset]]
        if strategy == "uncertainty":
            ordered_groups = (
                uncertainty_sorted[: pool_limit // 2],
                quality_sorted[: pool_limit // 3],
                least_compared_sorted[: pool_limit // 3],
            )
        else:
            ordered_groups = (
                quality_sorted[: pool_limit // 2],
                least_compared_sorted[: pool_limit // 2],
                uncertainty_sorted[: pool_limit // 3],
            )

        pool: list[Asset] = []
        seen_ids: set[str] = set()
        for group in ordered_groups:
            for asset in group:
                if asset.id in seen_ids:
                    continue
                pool.append(asset)
                seen_ids.add(asset.id)
                if len(pool) >= pool_limit:
                    return pool

        for asset in quality_sorted:
            if asset.id in seen_ids:
                continue
            pool.append(asset)
            seen_ids.add(asset.id)
            if len(pool) >= pool_limit:
                break
        return pool

    def _pick_smart_pair(
        self,
        assets: list[Asset],
        compared_pairs: set[tuple[str, str]],
        *,
        strategy: str,
    ) -> tuple[Asset, Asset] | None:
        if len(assets) < 2:
            return None

        best_score: float | None = None
        best_pair: tuple[Asset, Asset] | None = None

        # Adapted from QuentinWach/image-ranker's smart_shuffle():
        # prioritize close ratings and low comparison counts, then bias the
        # queue toward high-value LoRA candidates and, for uncertainty mode,
        # toward unresolved items.
        for idx, asset_a in enumerate(assets):
            for asset_b in assets[idx + 1:]:
                canonical = self._canonical_pair(asset_a.id, asset_b.id)
                if canonical in compared_pairs:
                    continue

                rating_gap = abs(self._ordinal(asset_a) - self._ordinal(asset_b))
                count_sum = float(
                    (asset_a.ranking_comparisons_count or 0)
                    + (asset_b.ranking_comparisons_count or 0)
                )
                quality_bonus = self._quality_priority(asset_a) + self._quality_priority(asset_b)
                sigma_bonus = float(asset_a.trueskill_sigma or 0.0) + float(asset_b.trueskill_sigma or 0.0)

                score = rating_gap + 0.8 * count_sum - 0.2 * quality_bonus
                if strategy == "uncertainty":
                    score -= 0.6 * sigma_bonus

                if best_score is None or score < best_score:
                    best_score = score
                    best_pair = (asset_a, asset_b)

        return best_pair

    def _pick_random_uncompared_pair(
        self,
        assets: list[Asset],
        compared_pairs: set[tuple[str, str]],
    ) -> tuple[Asset, Asset] | None:
        if len(assets) < 2:
            return None

        for _ in range(200):
            asset_a, asset_b = random.sample(assets, 2)
            if self._canonical_pair(asset_a.id, asset_b.id) not in compared_pairs:
                return asset_a, asset_b

        for idx, asset_a in enumerate(assets):
            for asset_b in assets[idx + 1:]:
                if self._canonical_pair(asset_a.id, asset_b.id) not in compared_pairs:
                    return asset_a, asset_b
        return None

    def _ordinal(self, asset: Asset) -> float:
        return float(asset.trueskill_mu or 0.0) - 3.0 * float(asset.trueskill_sigma or 0.0)

    def _quality_priority(self, asset: Asset) -> float:
        return (
            0.45 * float(asset.training_usefulness or 0.0)
            + 0.30 * float(asset.composite_score or 0.0)
            + 0.15 * float(asset.technical_quality or 0.0)
            + 0.10 * float(asset.face_quality or 0.0)
        )

    def _canonical_pair(self, asset_a_id: str, asset_b_id: str) -> tuple[str, str]:
        return tuple(sorted((asset_a_id, asset_b_id)))

    async def _replay_session_state(
        self,
        session: RankingSession,
        db: AsyncSession,
    ) -> None:
        if not session.asset_ids:
            return

        result = await db.execute(select(Asset).where(Asset.id.in_(session.asset_ids)))
        assets = {asset.id: asset for asset in result.scalars().all()}
        initial = session.initial_asset_ratings or {}

        for asset_id, asset in assets.items():
            snapshot = initial.get(asset_id)
            if snapshot is None:
                asset.trueskill_mu = _INITIAL_MU
                asset.trueskill_sigma = _INITIAL_SIGMA
                asset.elo_rating = 1500.0
                asset.ranking_comparisons_count = 0
            else:
                asset.trueskill_mu = float(snapshot.get("trueskill_mu", _INITIAL_MU))
                asset.trueskill_sigma = float(snapshot.get("trueskill_sigma", _INITIAL_SIGMA))
                asset.elo_rating = float(snapshot.get("elo_rating", 1500.0))
                asset.ranking_comparisons_count = int(snapshot.get("ranking_comparisons_count", 0))

        comparisons_result = await db.execute(
            select(RankingComparison)
            .where(RankingComparison.session_id == session.id)
            .order_by(RankingComparison.created_at.asc(), RankingComparison.id.asc())
        )
        comparisons = list(comparisons_result.scalars().all())
        engine = session.ranking_algorithm or "openskill"
        session.total_comparisons = len(comparisons)

        for comparison in comparisons:
            winner = assets.get(comparison.winner_asset_id)
            loser = assets.get(comparison.loser_asset_id)
            if winner is None or loser is None:
                continue
            draw = bool(comparison.is_draw)

            if engine == "openskill":
                w_mu, w_sigma, l_mu, l_sigma = self._apply_openskill(
                    winner.id,
                    winner.trueskill_mu,
                    winner.trueskill_sigma,
                    loser.id,
                    loser.trueskill_mu,
                    loser.trueskill_sigma,
                    draw=draw,
                )
                winner.trueskill_mu = w_mu
                winner.trueskill_sigma = w_sigma
                loser.trueskill_mu = l_mu
                loser.trueskill_sigma = l_sigma
            else:
                w_elo, l_elo = self._apply_elo(winner.elo_rating, loser.elo_rating, draw=draw)
                winner.elo_rating = w_elo
                loser.elo_rating = l_elo
                winner.trueskill_mu = w_elo / 60.0
                loser.trueskill_mu = l_elo / 60.0

            winner.ranking_comparisons_count = (winner.ranking_comparisons_count or 0) + 1
            loser.ranking_comparisons_count = (loser.ranking_comparisons_count or 0) + 1


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
    pair = await svc.get_next_pair(session.id, db, strategy=session.selection_strategy)
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
