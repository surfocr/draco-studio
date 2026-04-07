"""Add identity_consistency_score to identity_clusters

Revision ID: 0007_face_consistency
Revises: 0006_ranking_comparison_draw
Create Date: 2026-04-07
"""
from alembic import op
import sqlalchemy as sa


revision = "0007_face_consistency"
down_revision = "0006_ranking_comparison_draw"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "identity_clusters",
        sa.Column("identity_consistency_score", sa.Float(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("identity_clusters", "identity_consistency_score")
