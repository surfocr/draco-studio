"""UserPreferences ORM model — single-row global settings table."""
from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import Boolean, DateTime, Integer, JSON, String
from sqlalchemy.orm import Mapped, mapped_column

from database import Base


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class UserPreferences(Base):
    __tablename__ = "user_preferences"

    # Single-row table — always id=1
    id: Mapped[int] = mapped_column(Integer, primary_key=True, default=1)

    # UI preferences
    theme: Mapped[str] = mapped_column(String(16), default="dark")
    gallery_zoom: Mapped[int] = mapped_column(Integer, default=1)  # 0/1/2
    sidebar_collapsed: Mapped[bool] = mapped_column(Boolean, default=False)
    default_sort_by: Mapped[str] = mapped_column(String(32), default="composite_score")
    default_sort_dir: Mapped[str] = mapped_column(String(4), default="desc")

    # Analysis preferences
    auto_analyze_on_import: Mapped[bool] = mapped_column(Boolean, default=True)
    auto_caption_on_import: Mapped[bool] = mapped_column(Boolean, default=False)
    default_caption_provider: Mapped[str | None] = mapped_column(String(64), nullable=True)
    default_caption_style: Mapped[str] = mapped_column(String(32), default="natural")

    # Quality thresholds
    min_quality_for_export: Mapped[float] = mapped_column(default=0.5)
    auto_reject_below: Mapped[float | None] = mapped_column(nullable=True)
    # None = no auto-reject

    # Duplicate handling
    duplicate_action: Mapped[str] = mapped_column(String(16), default="flag")
    # "flag"/"auto_reject"/"ignore"

    # Extra JSON for extensibility
    extra: Mapped[dict | None] = mapped_column(JSON, nullable=True)

    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, onupdate=_utcnow
    )
