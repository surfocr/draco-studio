"""RankingSession and RankingComparison ORM models."""
from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy import Boolean, DateTime, Float, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from database import Base


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class RankingSession(Base):
    __tablename__ = "ranking_sessions"

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid.uuid4())
    )
    project_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False, default="Default Session")
    ranking_algorithm: Mapped[str] = mapped_column(String(32), default="openskill")
    # "openskill" / "elo"

    # Session state
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    total_comparisons: Mapped[int] = mapped_column(Integer, default=0)

    # AI judge config
    ai_judge_enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    ai_judge_provider: Mapped[str | None] = mapped_column(String(64), nullable=True)
    ai_judge_model: Mapped[str | None] = mapped_column(String(128), nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, onupdate=_utcnow
    )

    comparisons: Mapped[list[RankingComparison]] = relationship(
        "RankingComparison",
        back_populates="session",
        cascade="all, delete-orphan",
    )


class RankingComparison(Base):
    __tablename__ = "ranking_comparisons"

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid.uuid4())
    )
    session_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("ranking_sessions.id", ondelete="CASCADE"), nullable=False, index=True
    )
    project_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True
    )

    winner_asset_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("assets.id"), nullable=False
    )
    loser_asset_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("assets.id"), nullable=False
    )

    # Skill change
    winner_mu_before: Mapped[float | None] = mapped_column(Float, nullable=True)
    winner_mu_after: Mapped[float | None] = mapped_column(Float, nullable=True)
    loser_mu_before: Mapped[float | None] = mapped_column(Float, nullable=True)
    loser_mu_after: Mapped[float | None] = mapped_column(Float, nullable=True)

    # AI judge output
    ai_explanation: Mapped[str | None] = mapped_column(Text, nullable=True)
    ai_confidence: Mapped[float | None] = mapped_column(Float, nullable=True)
    judge_preferred: Mapped[str | None] = mapped_column(String(36), nullable=True)
    # asset_id of the AI's preferred image (may differ from human choice)

    # Source: "human" or "ai"
    decided_by: Mapped[str] = mapped_column(String(8), default="human")
    latency_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow
    )

    session: Mapped[RankingSession] = relationship(
        "RankingSession", back_populates="comparisons"
    )
