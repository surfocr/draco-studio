"""
OpenSkillRankingEngine — TrueSkill-style Bayesian ranking via openskill library.

Each asset has (mu, sigma):
  mu    = skill estimate (higher = better)
  sigma = uncertainty (decreases with each comparison)

Default priors: mu=25.0, sigma=8.333 (same as TrueSkill defaults).
Active learning pair selection: pick the pair with highest combined sigma.
"""
from __future__ import annotations

import logging
import random
from dataclasses import dataclass
from typing import Any

logger = logging.getLogger(__name__)

try:
    import openskill
    from openskill.models import PlackettLuce
    _OPENSKILL_AVAILABLE = True
except ImportError:
    _OPENSKILL_AVAILABLE = False
    logger.warning("openskill not installed — OpenSkillRankingEngine unavailable")


_DEFAULT_MU = 25.0
_DEFAULT_SIGMA = 25.0 / 3.0  # ≈ 8.333


@dataclass
class Rating:
    mu: float = _DEFAULT_MU
    sigma: float = _DEFAULT_SIGMA

    @property
    def ordinal(self) -> float:
        """Conservative rating: mu - 3*sigma."""
        return self.mu - 3.0 * self.sigma

    @property
    def confidence(self) -> float:
        """1.0 = fully certain, 0.0 = completely uncertain."""
        return max(0.0, 1.0 - self.sigma / _DEFAULT_SIGMA)


@dataclass
class RankingEntry:
    asset_id: str
    rank: int
    mu: float
    sigma: float
    ordinal: float
    confidence: float
    comparisons: int = 0


class OpenSkillRankingEngine:
    """
    TrueSkill-style Bayesian ranking.
    Maintains per-asset Rating(mu, sigma).

    NOTE: Does not inherit from ProviderBase ABC because the ranking
    service uses this class directly with its sync API. The ProviderBase
    compliance methods (is_available, health_check) are provided as async
    classmethods for registry compatibility.
    """

    provider_id = "openskill"
    display_name = "OpenSkill (TrueSkill-style)"
    provider_type = "ranking"

    def __init__(self, **kwargs) -> None:
        if not _OPENSKILL_AVAILABLE:
            raise ImportError("openskill library not installed. Run: pip install openskill")
        self._model = PlackettLuce()
        self._ratings: dict[str, Rating] = {}
        self._comparisons: dict[str, int] = {}  # asset_id → count

    async def is_available(self) -> bool:
        return _OPENSKILL_AVAILABLE

    async def health_check(self) -> dict[str, Any]:
        return {
            "ok": _OPENSKILL_AVAILABLE,
            "provider": "openskill",
            "latency_ms": 0,
            "details": {"ratings_count": len(self._ratings)},
        }

    def _get_or_create(self, asset_id: str) -> Rating:
        if asset_id not in self._ratings:
            self._ratings[asset_id] = Rating()
            self._comparisons[asset_id] = 0
        return self._ratings[asset_id]

    def add_asset(self, asset_id: str, mu: float | None = None, sigma: float | None = None) -> None:
        r = self._get_or_create(asset_id)
        if mu is not None:
            r.mu = mu
        if sigma is not None:
            r.sigma = sigma

    def rate_pair(
        self, winner_id: str, loser_id: str, weight: float = 1.0
    ) -> tuple[Rating, Rating]:
        """Apply TrueSkill update for winner > loser."""
        w_rating = self._get_or_create(winner_id)
        l_rating = self._get_or_create(loser_id)

        w_os = openskill.Rating(mu=w_rating.mu, sigma=w_rating.sigma)
        l_os = openskill.Rating(mu=l_rating.mu, sigma=l_rating.sigma)

        [[new_w], [new_l]] = self._model.rate([[w_os], [l_os]])

        w_rating.mu = new_w.mu
        w_rating.sigma = new_w.sigma
        l_rating.mu = new_l.mu
        l_rating.sigma = new_l.sigma

        self._comparisons[winner_id] = self._comparisons.get(winner_id, 0) + 1
        self._comparisons[loser_id] = self._comparisons.get(loser_id, 0) + 1

        return w_rating, l_rating

    def rate_draw(self, id_a: str, id_b: str) -> tuple[Rating, Rating]:
        """Apply TrueSkill update for a draw."""
        r_a = self._get_or_create(id_a)
        r_b = self._get_or_create(id_b)

        a_os = openskill.Rating(mu=r_a.mu, sigma=r_a.sigma)
        b_os = openskill.Rating(mu=r_b.mu, sigma=r_b.sigma)

        # Draw: rate as tie [[a],[b]] with rank [1,1]
        [[new_a], [new_b]] = self._model.rate([[a_os], [b_os]], ranks=[1, 1])

        r_a.mu = new_a.mu
        r_a.sigma = new_a.sigma
        r_b.mu = new_b.mu
        r_b.sigma = new_b.sigma

        self._comparisons[id_a] = self._comparisons.get(id_a, 0) + 1
        self._comparisons[id_b] = self._comparisons.get(id_b, 0) + 1

        return r_a, r_b

    def get_ratings(self) -> dict[str, Rating]:
        """Return ratings sorted by mu descending."""
        return dict(sorted(self._ratings.items(), key=lambda kv: kv[1].mu, reverse=True))

    def get_rating(self, asset_id: str) -> Rating:
        return self._get_or_create(asset_id)

    def get_leaderboard(self, top_n: int | None = None) -> list[RankingEntry]:
        sorted_items = sorted(self._ratings.items(), key=lambda kv: kv[1].ordinal, reverse=True)
        if top_n:
            sorted_items = sorted_items[:top_n]
        return [
            RankingEntry(
                asset_id=aid,
                rank=idx + 1,
                mu=r.mu,
                sigma=r.sigma,
                ordinal=r.ordinal,
                confidence=r.confidence,
                comparisons=self._comparisons.get(aid, 0),
            )
            for idx, (aid, r) in enumerate(sorted_items)
        ]

    def select_next_pair(self, strategy: str = "uncertainty") -> tuple[str, str] | None:
        """
        Select the next pair to compare.

        Strategies:
          uncertainty — pick the two assets with highest combined sigma
          random      — uniform random pair
          balanced    — mix: 70% uncertainty, 30% random
        """
        ids = list(self._ratings.keys())
        if len(ids) < 2:
            return None

        if strategy == "random":
            a, b = random.sample(ids, 2)
            return a, b

        if strategy == "balanced":
            if random.random() < 0.7:
                return self._select_uncertainty_pair(ids)
            a, b = random.sample(ids, 2)
            return a, b

        # Default: uncertainty
        return self._select_uncertainty_pair(ids)

    def _select_uncertainty_pair(self, ids: list[str]) -> tuple[str, str] | None:
        # Sort by sigma desc — pick top candidates
        sorted_ids = sorted(ids, key=lambda aid: self._ratings[aid].sigma, reverse=True)
        candidates = sorted_ids[:min(10, len(sorted_ids))]
        if len(candidates) < 2:
            candidates = sorted_ids[:2] if len(sorted_ids) >= 2 else sorted_ids
        if len(candidates) < 2:
            return None
        # Pick the pair with the highest combined sigma from candidates
        best: tuple[str, str] | None = None
        best_score = -1.0
        for i in range(min(len(candidates), 5)):
            for j in range(i + 1, min(len(candidates), 5)):
                score = self._ratings[candidates[i]].sigma + self._ratings[candidates[j]].sigma
                if score > best_score:
                    best_score = score
                    best = (candidates[i], candidates[j])
        return best

    def get_confidence(self, asset_id: str) -> float:
        return self._get_or_create(asset_id).confidence

    def export_ratings(self) -> list[dict[str, Any]]:
        return [
            {
                "asset_id": aid,
                "mu": r.mu,
                "sigma": r.sigma,
                "comparisons": self._comparisons.get(aid, 0),
            }
            for aid, r in self._ratings.items()
        ]

    def import_ratings(self, data: list[dict[str, Any]]) -> None:
        for entry in data:
            aid = entry["asset_id"]
            self._ratings[aid] = Rating(mu=entry["mu"], sigma=entry["sigma"])
            self._comparisons[aid] = entry.get("comparisons", 0)
