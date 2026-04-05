"""CaptionVersion ORM model."""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import TYPE_CHECKING

from sqlalchemy import Boolean, DateTime, Float, ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from database import Base

if TYPE_CHECKING:
    from models.asset import Asset


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class CaptionVersion(Base):
    __tablename__ = "caption_versions"

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid.uuid4())
    )
    asset_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("assets.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    # Caption content
    text: Mapped[str] = mapped_column(Text, nullable=False)
    style: Mapped[str] = mapped_column(
        String(32), nullable=False, default="natural"
    )
    # "natural"/"concise"/"danbooru_tags"/"wd_tags"/"training_literal"

    # Provider metadata
    provider: Mapped[str] = mapped_column(String(64), nullable=False)
    model: Mapped[str | None] = mapped_column(String(128), nullable=True)
    confidence: Mapped[float | None] = mapped_column(Float, nullable=True)
    latency_ms: Mapped[int | None] = mapped_column(nullable=True)

    # Flags
    is_edited: Mapped[bool] = mapped_column(Boolean, default=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=False)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow
    )
    edited_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    # Relationship back to asset
    asset: Mapped[Asset] = relationship(
        "Asset",
        back_populates="caption_versions",
        foreign_keys=[asset_id],
    )
