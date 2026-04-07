"""Persist draw state on ranking comparisons.

Revision ID: 0006_ranking_comparison_draw
Revises: 0005_ranking_session_state
Create Date: 2026-04-06
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "0006_ranking_comparison_draw"
down_revision = "0005_ranking_session_state"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "ranking_comparisons",
        sa.Column("is_draw", sa.Boolean(), nullable=False, server_default="0"),
    )


def downgrade() -> None:
    op.drop_column("ranking_comparisons", "is_draw")
