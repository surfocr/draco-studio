"""Per-project runtime and provider selection settings."""
from __future__ import annotations

from datetime import datetime, timezone
from typing import TYPE_CHECKING

from sqlalchemy import DateTime, ForeignKey, JSON, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from database import Base

if TYPE_CHECKING:
    from models.project import Project


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class ProjectRuntimeConfig(Base):
    __tablename__ = "project_runtime_configs"

    project_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("projects.id", ondelete="CASCADE"),
        primary_key=True,
    )

    runtime_mode: Mapped[str] = mapped_column(String(16), default="local")
    task_provider_overrides: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    task_provider_options: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    benchmark_preferences: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, onupdate=_utcnow
    )

    project: Mapped[Project] = relationship("Project", back_populates="runtime_config")
