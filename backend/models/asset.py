"""
Asset ORM model — the central entity.
Contains every analysis field produced by the pipeline.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from enum import Enum
from typing import TYPE_CHECKING

from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from database import Base

if TYPE_CHECKING:
    from models.project import Project
    from models.caption import CaptionVersion


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class ReviewState(str, Enum):
    PENDING = "pending"
    REVIEWED = "reviewed"
    APPROVED = "approved"
    REJECTED = "rejected"
    FLAGGED = "flagged"


class ShotType(str, Enum):
    EXTREME_CLOSEUP = "extreme_closeup"
    CLOSEUP = "closeup"
    MEDIUM = "medium"
    WIDE = "wide"
    FULL_BODY = "full_body"
    UNKNOWN = "unknown"


class ExportState(str, Enum):
    NOT_EXPORTED = "not_exported"
    EXPORTED = "exported"
    EXCLUDED = "excluded"


class Asset(Base):
    __tablename__ = "assets"

    # ── Core identity ──────────────────────────────────────────────────────────
    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid.uuid4())
    )
    project_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True
    )
    filename: Mapped[str] = mapped_column(String(512), nullable=False)
    filepath: Mapped[str] = mapped_column(Text, nullable=False)          # Absolute FS path
    file_size: Mapped[int | None] = mapped_column(Integer, nullable=True)
    mime_type: Mapped[str | None] = mapped_column(String(64), nullable=True)

    # ── Dimensions ────────────────────────────────────────────────────────────
    width: Mapped[int | None] = mapped_column(Integer, nullable=True)
    height: Mapped[int | None] = mapped_column(Integer, nullable=True)

    # ── Perceptual hashes ─────────────────────────────────────────────────────
    sha256_hash: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    phash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    dhash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    ahash: Mapped[str | None] = mapped_column(String(64), nullable=True)

    # ── Timestamps ────────────────────────────────────────────────────────────
    imported_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, index=True
    )
    analyzed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, index=True
    )
    modified_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, onupdate=_utcnow
    )

    # ── Thumbnails ────────────────────────────────────────────────────────────
    thumbnail_path: Mapped[str | None] = mapped_column(Text, nullable=True)
    thumbnail_small_path: Mapped[str | None] = mapped_column(Text, nullable=True)

    # ── Face analysis ─────────────────────────────────────────────────────────
    face_count: Mapped[int] = mapped_column(Integer, default=0, index=True)
    primary_face_bbox: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    # {"x1": float, "y1": float, "x2": float, "y2": float, "confidence": float}
    face_sharpness: Mapped[float | None] = mapped_column(Float, nullable=True)
    face_embedding_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    identity_cluster_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("identity_clusters.id"), nullable=True, index=True
    )
    identity_confidence: Mapped[float | None] = mapped_column(Float, nullable=True)
    landmark_confidence: Mapped[float | None] = mapped_column(Float, nullable=True)

    # Age/gender/emotion (from InsightFace buffalo_l attribute model)
    age_estimate: Mapped[float | None] = mapped_column(Float, nullable=True)
    gender_estimate: Mapped[str | None] = mapped_column(String(16), nullable=True)  # "male"/"female"
    dominant_emotion: Mapped[str | None] = mapped_column(String(32), nullable=True)

    # Head pose
    head_pose_yaw: Mapped[float | None] = mapped_column(Float, nullable=True)
    head_pose_pitch: Mapped[float | None] = mapped_column(Float, nullable=True)
    head_pose_roll: Mapped[float | None] = mapped_column(Float, nullable=True)

    # Gaze / eye analysis
    gaze_direction: Mapped[str | None] = mapped_column(String(32), nullable=True)
    # "forward"/"left"/"right"/"up"/"down"/"closed"
    occlusion_flags: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    # {"left_eye": bool, "right_eye": bool, "nose": bool, "mouth": bool}
    eyewear_detected: Mapped[bool] = mapped_column(Boolean, default=False)
    action_units: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    # {"AU1": float, "AU2": float, ...}

    # ── Pose / framing ─────────────────────────────────────────────────────────
    shot_type: Mapped[str] = mapped_column(
        String(32), default=ShotType.UNKNOWN.value
    )
    body_pose_type: Mapped[str | None] = mapped_column(String(64), nullable=True)
    limb_visibility: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    # {"left_arm": bool, "right_arm": bool, "torso": bool, "legs": bool}
    camera_angle_hint: Mapped[str | None] = mapped_column(String(32), nullable=True)
    # "front"/"side"/"back"/"above"/"below"
    crop_tightness: Mapped[float | None] = mapped_column(Float, nullable=True)
    # 0.0 (loose) – 1.0 (very tight)
    composition_score: Mapped[float | None] = mapped_column(Float, nullable=True)

    # ── Scene understanding ───────────────────────────────────────────────────
    is_indoor: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    scene_class: Mapped[str | None] = mapped_column(String(64), nullable=True)
    background_clutter_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    object_tags: Mapped[list[str] | None] = mapped_column(JSON, nullable=True)
    scene_tags: Mapped[list[str] | None] = mapped_column(JSON, nullable=True)
    lighting_tags: Mapped[list[str] | None] = mapped_column(JSON, nullable=True)
    dof_estimate: Mapped[str | None] = mapped_column(String(16), nullable=True)
    # "shallow"/"medium"/"deep"
    has_plain_background: Mapped[bool | None] = mapped_column(Boolean, nullable=True)

    # ── Caption state ─────────────────────────────────────────────────────────
    active_caption_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("caption_versions.id"), nullable=True
    )
    caption_provider: Mapped[str | None] = mapped_column(String(64), nullable=True)

    # ── Quality scores ────────────────────────────────────────────────────────
    technical_quality: Mapped[float | None] = mapped_column(Float, nullable=True, index=True)
    # 0.0–1.0: sharpness, resolution, noise
    aesthetic_score: Mapped[float | None] = mapped_column(Float, nullable=True, index=True)
    # 0.0–1.0: LAION aesthetic predictor or heuristic
    face_quality: Mapped[float | None] = mapped_column(Float, nullable=True, index=True)
    # 0.0–1.0: InsightFace det_score, face sharpness
    training_usefulness: Mapped[float | None] = mapped_column(Float, nullable=True)
    # 0.0–1.0: overall training value estimate
    uniqueness_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    # 0.0–1.0: 1 = completely unique, 0 = many near-duplicates
    redundancy_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    # 0.0–1.0: how redundant this asset is in the dataset
    composite_score: Mapped[float | None] = mapped_column(Float, nullable=True, index=True)
    # DracoFlow v4 weighted composite
    score_breakdown: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    # {"sharpness": 0.85, "aesthetic": 0.72, ...}

    # ── Review state ──────────────────────────────────────────────────────────
    review_state: Mapped[str] = mapped_column(
        String(16), default=ReviewState.PENDING.value, index=True
    )
    is_rejected: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    is_flagged: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    rejection_reason: Mapped[str | None] = mapped_column(Text, nullable=True)

    # ── Augmentation ─────────────────────────────────────────────────────────
    is_augmented: Mapped[bool] = mapped_column(Boolean, default=False)
    augmentation_source_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("assets.id"), nullable=True
    )
    augmentation_type: Mapped[str | None] = mapped_column(String(64), nullable=True)
    # "outpaint"/"background_replace"/"expression_edit"

    # ── Export state ──────────────────────────────────────────────────────────
    export_state: Mapped[str] = mapped_column(
        String(16), default=ExportState.NOT_EXPORTED.value
    )
    export_metadata: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    # {"last_exported_at": str, "export_format": str, "export_job_id": str}

    # ── Duplicate tracking ────────────────────────────────────────────────────
    duplicate_cluster_id: Mapped[str | None] = mapped_column(
        String(36), nullable=True, index=True
    )
    duplicate_type: Mapped[str | None] = mapped_column(String(16), nullable=True)
    # "exact"/"phash"/"embedding"/"face"

    # ── Ranking ───────────────────────────────────────────────────────────────
    trueskill_mu: Mapped[float] = mapped_column(Float, default=25.0, index=True)
    trueskill_sigma: Mapped[float] = mapped_column(Float, default=8.333)
    elo_rating: Mapped[float] = mapped_column(Float, default=1500.0)
    ranking_comparisons_count: Mapped[int] = mapped_column(Integer, default=0)

    # ── Relationships ─────────────────────────────────────────────────────────
    project: Mapped[Project] = relationship("Project", back_populates="assets")
    caption_versions: Mapped[list[CaptionVersion]] = relationship(
        "CaptionVersion",
        primaryjoin="Asset.id == CaptionVersion.asset_id",
        back_populates="asset",
        cascade="all, delete-orphan",
        foreign_keys="CaptionVersion.asset_id",
    )
    augmentation_children: Mapped[list[Asset]] = relationship(
        "Asset",
        primaryjoin="Asset.id == Asset.augmentation_source_id",
        foreign_keys="Asset.augmentation_source_id",
    )
