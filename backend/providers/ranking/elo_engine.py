"""
EloRankingEngine — Simple Elo rating system.
K=32 by default. Starting rating 1500.
"""
from __future__ import annotations

import logging
import random
from dataclasses import dataclass
from typing import Any

logger = logging.getLogger(__name__)


@dataclass
class RankingEntry:
    asset_id: str
    rank: int
    elo: float
    comparisons: int = 0


class EloRankingEngine:
    K_FACTOR = 32
    DEFAULT_RATING = 1500.0

    def __init__(self) -> None:
        self._ratings: dict[str, float] = {}
        self._comparisons: dict[str, int] = {}

    def _get_or_create(self, asset_id: str) -> float:
        if asset_id not in self._ratings:
            self._ratings[asset_id] = self.DEFAULT_RATING
            self._comparisons[asset_id] = 0
        return self._ratings[asset_id]

    def add_asset(self, asset_id: str, rating: float | None = None) -> None:
        if asset_id not in self._ratings:
            self._ratings[asset_id] = rating if rating is not None else self.DEFAULT_RATING
            self._comparisons[asset_id] = 0

    def rate_pair(self, winner_id: str, loser_id: str) -> tuple[float, float]:
        """Update Elo for winner/loser. Returns (new_winner_elo, new_loser_elo)."""
        w_elo = self._get_or_create(winner_id)
        l_elo = self._get_or_create(loser_id)

        expected_w = 1.0 / (1.0 + 10 ** ((l_elo - w_elo) / 400.0))
        expected_l = 1.0 - expected_w

        new_w = w_elo + self.K_FACTOR * (1.0 - expected_w)
        new_l = l_elo + self.K_FACTOR * (0.0 - expected_l)

        self._ratings[winner_id] = new_w
        self._ratings[loser_id] = new_l
        self._comparisons[winner_id] = self._comparisons.get(winner_id, 0) + 1
        self._comparisons[loser_id] = self._comparisons.get(loser_id, 0) + 1

        return new_w, new_l

    def rate_draw(self, id_a: str, id_b: str) -> tuple[float, float]:
        a_elo = self._get_or_create(id_a)
        b_elo = self._get_or_create(id_b)

        expected_a = 1.0 / (1.0 + 10 ** ((b_elo - a_elo) / 400.0))
        expected_b = 1.0 - expected_a

        new_a = a_elo + self.K_FACTOR * (0.5 - expected_a)
        new_b = b_elo + self.K_FACTOR * (0.5 - expected_b)

        self._ratings[id_a] = new_a
        self._ratings[id_b] = new_b
        self._comparisons[id_a] = self._comparisons.get(id_a, 0) + 1
        self._comparisons[id_b] = self._comparisons.get(id_b, 0) + 1

        return new_a, new_b

    def get_ratings(self) -> dict[str, float]:
        return dict(sorted(self._ratings.items(), key=lambda kv: kv[1], reverse=True))

    def get_rating(self, asset_id: str) -> float:
        return self._get_or_create(asset_id)

    def get_leaderboard(self, top_n: int | None = None) -> list[RankingEntry]:
        sorted_items = sorted(self._ratings.items(), key=lambda kv: kv[1], reverse=True)
        if top_n:
            sorted_items = sorted_items[:top_n]
        return [
            RankingEntry(
                asset_id=aid,
                rank=idx + 1,
                elo=elo,
                comparisons=self._comparisons.get(aid, 0),
            )
            for idx, (aid, elo) in enumerate(sorted_items)
        ]

    def select_next_pair(self, strategy: str = "random") -> tuple[str, str] | None:
        ids = list(self._ratings.keys())
        if len(ids) < 2:
            return None

        if strategy == "closest":
            # Match assets with similar ratings
            sorted_ids = sorted(ids, key=lambda aid: self._ratings[aid])
            idx = random.randint(0, len(sorted_ids) - 2)
            return sorted_ids[idx], sorted_ids[idx + 1]

        a, b = random.sample(ids, 2)
        return a, b

    def export_ratings(self) -> list[dict[str, Any]]:
        return [
            {
                "asset_id": aid,
                "elo": elo,
                "comparisons": self._comparisons.get(aid, 0),
            }
            for aid, elo in self._ratings.items()
        ]

    def import_ratings(self, data: list[dict[str, Any]]) -> None:
        for entry in data:
            aid = entry["asset_id"]
            self._ratings[aid] = entry.get("elo", self.DEFAULT_RATING)
            self._comparisons[aid] = entry.get("comparisons", 0)
