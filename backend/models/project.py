"""Project ORM model."""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import TYPE_CHECKING

from sqlalchemy import DateTime, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from database import Base

if TYPE_CHECKING:
    from models.asset import Asset
    from models.project_runtime_config import ProjectRuntimeConfig


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Project(Base):
    __tablename__ = "projects"

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid.uuid4())
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    trigger_word: Mapped[str | None] = mapped_column(String(255), nullable=True)
    subject_type: Mapped[str | None] = mapped_column(String(64), nullable=True)
    storage_path: Mapped[str | None] = mapped_column(Text, nullable=True)
    thumbnail_asset_id: Mapped[str | None] = mapped_column(String(36), nullable=True)

    # Stats (denormalized for fast dashboard rendering)
    asset_count: Mapped[int] = mapped_column(default=0)
    reviewed_count: Mapped[int] = mapped_column(default=0)
    flagged_count: Mapped[int] = mapped_column(default=0)
    rejected_count: Mapped[int] = mapped_column(default=0)

    # Timestamps
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, onupdate=_utcnow
    )

    # Relationships
    assets: Mapped[list[Asset]] = relationship(
        "Asset", back_populates="project", cascade="all, delete-orphan"
    )
    runtime_config: Mapped[ProjectRuntimeConfig | None] = relationship(
        "ProjectRuntimeConfig",
        back_populates="project",
        uselist=False,
        cascade="all, delete-orphan",
    )
