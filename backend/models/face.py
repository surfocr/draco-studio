"""FaceCluster and IdentityCluster ORM models."""
from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy import JSON, Boolean, DateTime, Float, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from database import Base


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class FaceCluster(Base):
    """
    A cluster of face detections across multiple assets that belong to the
    same identity (or are unknown). Multiple FaceClusters may later be merged
    into an IdentityCluster.
    """
    __tablename__ = "face_clusters"

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid.uuid4())
    )
    project_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True
    )
    identity_cluster_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("identity_clusters.id"), nullable=True, index=True
    )

    # Cluster stats
    member_count: Mapped[int] = mapped_column(Integer, default=0)
    mean_embedding: Mapped[list | None] = mapped_column(JSON, nullable=True)
    # Stored as list[float] — centroid of all face embeddings in this cluster
    representative_asset_id: Mapped[str | None] = mapped_column(
        String(36), nullable=True
    )

    # Clustering metadata
    cluster_algorithm: Mapped[str | None] = mapped_column(String(32), nullable=True)
    cluster_confidence: Mapped[float | None] = mapped_column(Float, nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, onupdate=_utcnow
    )


class IdentityCluster(Base):
    """
    A named identity. May encompass multiple FaceClusters (e.g. after manual merge).
    This is the "person" concept — e.g. "Subject A", "Person #3".
    """
    __tablename__ = "identity_clusters"

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid.uuid4())
    )
    project_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True
    )

    # Identity info
    label: Mapped[str] = mapped_column(String(255), nullable=False)
    # User-assigned name or auto-generated "Person #1"
    is_subject: Mapped[bool] = mapped_column(Boolean, default=False)
    # True = this is the primary training subject

    thumbnail_asset_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    asset_count: Mapped[int] = mapped_column(Integer, default=0)
    mean_age_estimate: Mapped[float | None] = mapped_column(Float, nullable=True)
    dominant_gender: Mapped[str | None] = mapped_column(String(16), nullable=True)

    notes: Mapped[str | None] = mapped_column(Text, nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, onupdate=_utcnow
    )

    face_clusters: Mapped[list[FaceCluster]] = relationship(
        "FaceCluster",
        primaryjoin="FaceCluster.identity_cluster_id == IdentityCluster.id",
        foreign_keys="FaceCluster.identity_cluster_id",
    )
