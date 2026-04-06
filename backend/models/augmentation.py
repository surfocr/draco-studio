"""AugmentationJob and AugmentationResult ORM models."""
from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy import JSON, DateTime, Float, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from database import Base


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class AugmentationJob(Base):
    __tablename__ = "augmentation_jobs"

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid.uuid4())
    )
    project_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True
    )
    source_asset_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("assets.id"), nullable=False
    )

    # Job config
    augmentation_type: Mapped[str] = mapped_column(String(64), nullable=False)
    # "outpaint"/"background_replace"/"expression_edit"/"flip"/"color_jitter"
    provider: Mapped[str] = mapped_column(String(64), nullable=False)
    parameters: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    # Provider-specific parameters: {"direction": "right", "padding": 256, "prompt": "..."}

    # Status
    status: Mapped[str] = mapped_column(String(16), default="pending")
    # "pending"/"running"/"done"/"failed"/"cancelled"/"pending_review"/"approved"/"rejected"
    progress: Mapped[int] = mapped_column(Integer, default=0)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    external_job_id: Mapped[str | None] = mapped_column(String(256), nullable=True)

    # Output tracking
    output_path: Mapped[str | None] = mapped_column(Text, nullable=True)
    before_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    after_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    identity_preserved: Mapped[bool | None] = mapped_column(nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow
    )
    started_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    finished_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    results: Mapped[list[AugmentationResult]] = relationship(
        "AugmentationResult",
        back_populates="job",
        cascade="all, delete-orphan",
    )


class AugmentationResult(Base):
    __tablename__ = "augmentation_results"

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid.uuid4())
    )
    job_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("augmentation_jobs.id", ondelete="CASCADE"), nullable=False
    )
    result_asset_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("assets.id"), nullable=True
    )
    # Null until the result image is ingested as an Asset

    seed: Mapped[int | None] = mapped_column(Integer, nullable=True)
    generation_params: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    quality_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    accepted: Mapped[bool | None] = mapped_column(nullable=True)
    # None = not yet reviewed

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow
    )

    job: Mapped[AugmentationJob] = relationship(
        "AugmentationJob", back_populates="results"
    )
