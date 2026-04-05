"""Initial schema — all tables.

Revision ID: 0001
Revises:
Create Date: 2026-04-04
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    # projects
    op.create_table(
        "projects",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("description", sa.Text, nullable=True),
        sa.Column("trigger_word", sa.String(255), nullable=True),
        sa.Column("subject_type", sa.String(64), nullable=True),
        sa.Column("storage_path", sa.Text, nullable=True),
        sa.Column("thumbnail_asset_id", sa.String(36), nullable=True),
        sa.Column("asset_count", sa.Integer, nullable=False, server_default="0"),
        sa.Column("reviewed_count", sa.Integer, nullable=False, server_default="0"),
        sa.Column("flagged_count", sa.Integer, nullable=False, server_default="0"),
        sa.Column("rejected_count", sa.Integer, nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )

    # identity_clusters (before assets for FK)
    op.create_table(
        "identity_clusters",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("project_id", sa.String(36), sa.ForeignKey("projects.id", ondelete="CASCADE"), nullable=False),
        sa.Column("label", sa.String(255), nullable=False),
        sa.Column("is_subject", sa.Boolean, nullable=False, server_default="0"),
        sa.Column("thumbnail_asset_id", sa.String(36), nullable=True),
        sa.Column("asset_count", sa.Integer, nullable=False, server_default="0"),
        sa.Column("mean_age_estimate", sa.Float, nullable=True),
        sa.Column("dominant_gender", sa.String(16), nullable=True),
        sa.Column("notes", sa.Text, nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_identity_clusters_project_id", "identity_clusters", ["project_id"])

    # caption_versions (before assets for FK)
    op.create_table(
        "caption_versions",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("asset_id", sa.String(36), nullable=False),
        sa.Column("text", sa.Text, nullable=False),
        sa.Column("style", sa.String(32), nullable=False, server_default="natural"),
        sa.Column("provider", sa.String(64), nullable=False),
        sa.Column("model", sa.String(128), nullable=True),
        sa.Column("confidence", sa.Float, nullable=True),
        sa.Column("latency_ms", sa.Integer, nullable=True),
        sa.Column("is_edited", sa.Boolean, nullable=False, server_default="0"),
        sa.Column("is_active", sa.Boolean, nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("edited_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_caption_versions_asset_id", "caption_versions", ["asset_id"])

    # assets
    op.create_table(
        "assets",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("project_id", sa.String(36), sa.ForeignKey("projects.id", ondelete="CASCADE"), nullable=False),
        sa.Column("filename", sa.String(512), nullable=False),
        sa.Column("filepath", sa.Text, nullable=False),
        sa.Column("file_size", sa.Integer, nullable=True),
        sa.Column("mime_type", sa.String(64), nullable=True),
        sa.Column("width", sa.Integer, nullable=True),
        sa.Column("height", sa.Integer, nullable=True),
        sa.Column("sha256_hash", sa.String(64), nullable=True),
        sa.Column("phash", sa.String(64), nullable=True),
        sa.Column("dhash", sa.String(64), nullable=True),
        sa.Column("ahash", sa.String(64), nullable=True),
        sa.Column("imported_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("analyzed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("modified_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("thumbnail_path", sa.Text, nullable=True),
        sa.Column("thumbnail_small_path", sa.Text, nullable=True),
        # Face
        sa.Column("face_count", sa.Integer, nullable=False, server_default="0"),
        sa.Column("primary_face_bbox", sa.JSON, nullable=True),
        sa.Column("face_sharpness", sa.Float, nullable=True),
        sa.Column("face_embedding_id", sa.String(36), nullable=True),
        sa.Column("identity_cluster_id", sa.String(36), sa.ForeignKey("identity_clusters.id"), nullable=True),
        sa.Column("identity_confidence", sa.Float, nullable=True),
        sa.Column("landmark_confidence", sa.Float, nullable=True),
        sa.Column("age_estimate", sa.Float, nullable=True),
        sa.Column("gender_estimate", sa.String(16), nullable=True),
        sa.Column("dominant_emotion", sa.String(32), nullable=True),
        sa.Column("head_pose_yaw", sa.Float, nullable=True),
        sa.Column("head_pose_pitch", sa.Float, nullable=True),
        sa.Column("head_pose_roll", sa.Float, nullable=True),
        sa.Column("gaze_direction", sa.String(32), nullable=True),
        sa.Column("occlusion_flags", sa.JSON, nullable=True),
        sa.Column("eyewear_detected", sa.Boolean, nullable=False, server_default="0"),
        sa.Column("action_units", sa.JSON, nullable=True),
        # Pose/framing
        sa.Column("shot_type", sa.String(32), nullable=False, server_default="unknown"),
        sa.Column("body_pose_type", sa.String(64), nullable=True),
        sa.Column("limb_visibility", sa.JSON, nullable=True),
        sa.Column("camera_angle_hint", sa.String(32), nullable=True),
        sa.Column("crop_tightness", sa.Float, nullable=True),
        sa.Column("composition_score", sa.Float, nullable=True),
        # Scene
        sa.Column("is_indoor", sa.Boolean, nullable=True),
        sa.Column("scene_class", sa.String(64), nullable=True),
        sa.Column("background_clutter_score", sa.Float, nullable=True),
        sa.Column("object_tags", sa.JSON, nullable=True),
        sa.Column("scene_tags", sa.JSON, nullable=True),
        sa.Column("lighting_tags", sa.JSON, nullable=True),
        sa.Column("dof_estimate", sa.String(16), nullable=True),
        sa.Column("has_plain_background", sa.Boolean, nullable=True),
        # Caption
        sa.Column("active_caption_id", sa.String(36), sa.ForeignKey("caption_versions.id"), nullable=True),
        sa.Column("caption_provider", sa.String(64), nullable=True),
        # Quality
        sa.Column("technical_quality", sa.Float, nullable=True),
        sa.Column("aesthetic_score", sa.Float, nullable=True),
        sa.Column("face_quality", sa.Float, nullable=True),
        sa.Column("training_usefulness", sa.Float, nullable=True),
        sa.Column("uniqueness_score", sa.Float, nullable=True),
        sa.Column("redundancy_score", sa.Float, nullable=True),
        sa.Column("composite_score", sa.Float, nullable=True),
        sa.Column("score_breakdown", sa.JSON, nullable=True),
        # Review
        sa.Column("review_state", sa.String(16), nullable=False, server_default="pending"),
        sa.Column("is_rejected", sa.Boolean, nullable=False, server_default="0"),
        sa.Column("is_flagged", sa.Boolean, nullable=False, server_default="0"),
        sa.Column("rejection_reason", sa.Text, nullable=True),
        # Augmentation
        sa.Column("is_augmented", sa.Boolean, nullable=False, server_default="0"),
        sa.Column("augmentation_source_id", sa.String(36), sa.ForeignKey("assets.id"), nullable=True),
        sa.Column("augmentation_type", sa.String(64), nullable=True),
        # Export
        sa.Column("export_state", sa.String(16), nullable=False, server_default="not_exported"),
        sa.Column("export_metadata", sa.JSON, nullable=True),
        # Duplicates
        sa.Column("duplicate_cluster_id", sa.String(36), nullable=True),
        sa.Column("duplicate_type", sa.String(16), nullable=True),
        # Ranking
        sa.Column("trueskill_mu", sa.Float, nullable=False, server_default="25.0"),
        sa.Column("trueskill_sigma", sa.Float, nullable=False, server_default="8.333"),
        sa.Column("elo_rating", sa.Float, nullable=False, server_default="1500.0"),
        sa.Column("ranking_comparisons_count", sa.Integer, nullable=False, server_default="0"),
    )
    op.create_index("ix_assets_project_id", "assets", ["project_id"])
    op.create_index("ix_assets_sha256_hash", "assets", ["sha256_hash"])
    op.create_index("ix_assets_review_state", "assets", ["review_state"])
    op.create_index("ix_assets_is_flagged", "assets", ["is_flagged"])
    op.create_index("ix_assets_is_rejected", "assets", ["is_rejected"])
    op.create_index("ix_assets_identity_cluster_id", "assets", ["identity_cluster_id"])
    op.create_index("ix_assets_duplicate_cluster_id", "assets", ["duplicate_cluster_id"])

    # Add FK from caption_versions to assets
    op.create_foreign_key(
        "fk_caption_asset", "caption_versions", "assets", ["asset_id"], ["id"], ondelete="CASCADE"
    )

    # face_clusters
    op.create_table(
        "face_clusters",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("project_id", sa.String(36), sa.ForeignKey("projects.id", ondelete="CASCADE"), nullable=False),
        sa.Column("identity_cluster_id", sa.String(36), sa.ForeignKey("identity_clusters.id"), nullable=True),
        sa.Column("member_count", sa.Integer, nullable=False, server_default="0"),
        sa.Column("mean_embedding", sa.JSON, nullable=True),
        sa.Column("representative_asset_id", sa.String(36), nullable=True),
        sa.Column("cluster_algorithm", sa.String(32), nullable=True),
        sa.Column("cluster_confidence", sa.Float, nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )

    # ranking_sessions
    op.create_table(
        "ranking_sessions",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("project_id", sa.String(36), sa.ForeignKey("projects.id", ondelete="CASCADE"), nullable=False),
        sa.Column("name", sa.String(255), nullable=False, server_default="Default Session"),
        sa.Column("ranking_algorithm", sa.String(32), nullable=False, server_default="openskill"),
        sa.Column("is_active", sa.Boolean, nullable=False, server_default="1"),
        sa.Column("total_comparisons", sa.Integer, nullable=False, server_default="0"),
        sa.Column("ai_judge_enabled", sa.Boolean, nullable=False, server_default="0"),
        sa.Column("ai_judge_provider", sa.String(64), nullable=True),
        sa.Column("ai_judge_model", sa.String(128), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )

    # ranking_comparisons
    op.create_table(
        "ranking_comparisons",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("session_id", sa.String(36), sa.ForeignKey("ranking_sessions.id", ondelete="CASCADE"), nullable=False),
        sa.Column("project_id", sa.String(36), sa.ForeignKey("projects.id", ondelete="CASCADE"), nullable=False),
        sa.Column("winner_asset_id", sa.String(36), sa.ForeignKey("assets.id"), nullable=False),
        sa.Column("loser_asset_id", sa.String(36), sa.ForeignKey("assets.id"), nullable=False),
        sa.Column("winner_mu_before", sa.Float, nullable=True),
        sa.Column("winner_mu_after", sa.Float, nullable=True),
        sa.Column("loser_mu_before", sa.Float, nullable=True),
        sa.Column("loser_mu_after", sa.Float, nullable=True),
        sa.Column("ai_explanation", sa.Text, nullable=True),
        sa.Column("ai_confidence", sa.Float, nullable=True),
        sa.Column("judge_preferred", sa.String(36), nullable=True),
        sa.Column("decided_by", sa.String(8), nullable=False, server_default="human"),
        sa.Column("latency_ms", sa.Integer, nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )

    # augmentation_jobs
    op.create_table(
        "augmentation_jobs",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("project_id", sa.String(36), sa.ForeignKey("projects.id", ondelete="CASCADE"), nullable=False),
        sa.Column("source_asset_id", sa.String(36), sa.ForeignKey("assets.id"), nullable=False),
        sa.Column("augmentation_type", sa.String(64), nullable=False),
        sa.Column("provider", sa.String(64), nullable=False),
        sa.Column("parameters", sa.JSON, nullable=True),
        sa.Column("status", sa.String(16), nullable=False, server_default="pending"),
        sa.Column("progress", sa.Integer, nullable=False, server_default="0"),
        sa.Column("error_message", sa.Text, nullable=True),
        sa.Column("external_job_id", sa.String(256), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
    )

    # augmentation_results
    op.create_table(
        "augmentation_results",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("job_id", sa.String(36), sa.ForeignKey("augmentation_jobs.id", ondelete="CASCADE"), nullable=False),
        sa.Column("result_asset_id", sa.String(36), sa.ForeignKey("assets.id"), nullable=True),
        sa.Column("seed", sa.Integer, nullable=True),
        sa.Column("generation_params", sa.JSON, nullable=True),
        sa.Column("quality_score", sa.Float, nullable=True),
        sa.Column("accepted", sa.Boolean, nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )

    # export_jobs
    op.create_table(
        "export_jobs",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("project_id", sa.String(36), sa.ForeignKey("projects.id", ondelete="CASCADE"), nullable=False),
        sa.Column("export_format", sa.String(32), nullable=False),
        sa.Column("output_path", sa.Text, nullable=True),
        sa.Column("export_options", sa.JSON, nullable=True),
        sa.Column("total_assets", sa.Integer, nullable=False, server_default="0"),
        sa.Column("exported_assets", sa.Integer, nullable=False, server_default="0"),
        sa.Column("total_bytes", sa.Integer, nullable=False, server_default="0"),
        sa.Column("status", sa.String(16), nullable=False, server_default="pending"),
        sa.Column("progress", sa.Integer, nullable=False, server_default="0"),
        sa.Column("error_message", sa.Text, nullable=True),
        sa.Column("download_url", sa.Text, nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
    )

    # provider_configs
    op.create_table(
        "provider_configs",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("provider_type", sa.String(64), nullable=False),
        sa.Column("provider_name", sa.String(64), nullable=False),
        sa.Column("is_enabled", sa.Boolean, nullable=False, server_default="1"),
        sa.Column("is_default", sa.Boolean, nullable=False, server_default="0"),
        sa.Column("api_key_encrypted", sa.Text, nullable=True),
        sa.Column("config", sa.JSON, nullable=True),
        sa.Column("last_health_ok", sa.Boolean, nullable=True),
        sa.Column("last_health_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_health_error", sa.Text, nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )

    # user_preferences
    op.create_table(
        "user_preferences",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("theme", sa.String(16), nullable=False, server_default="dark"),
        sa.Column("gallery_zoom", sa.Integer, nullable=False, server_default="1"),
        sa.Column("sidebar_collapsed", sa.Boolean, nullable=False, server_default="0"),
        sa.Column("default_sort_by", sa.String(32), nullable=False, server_default="composite_score"),
        sa.Column("default_sort_dir", sa.String(4), nullable=False, server_default="desc"),
        sa.Column("auto_analyze_on_import", sa.Boolean, nullable=False, server_default="1"),
        sa.Column("auto_caption_on_import", sa.Boolean, nullable=False, server_default="0"),
        sa.Column("default_caption_provider", sa.String(64), nullable=True),
        sa.Column("default_caption_style", sa.String(32), nullable=False, server_default="natural"),
        sa.Column("min_quality_for_export", sa.Float, nullable=False, server_default="0.5"),
        sa.Column("auto_reject_below", sa.Float, nullable=True),
        sa.Column("duplicate_action", sa.String(16), nullable=False, server_default="flag"),
        sa.Column("extra", sa.JSON, nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )


def downgrade() -> None:
    op.drop_table("user_preferences")
    op.drop_table("provider_configs")
    op.drop_table("export_jobs")
    op.drop_table("augmentation_results")
    op.drop_table("augmentation_jobs")
    op.drop_table("ranking_comparisons")
    op.drop_table("ranking_sessions")
    op.drop_table("face_clusters")
    op.drop_table("assets")
    op.drop_table("caption_versions")
    op.drop_table("identity_clusters")
    op.drop_table("projects")
