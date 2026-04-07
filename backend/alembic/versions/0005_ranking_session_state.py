"""Add ranking session replay and skip state.

Revision ID: 0005_ranking_session_state
Revises: 0004_ranking_session_scope
Create Date: 2026-04-06
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "0005_ranking_session_state"
down_revision = "0004_ranking_session_scope"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "ranking_sessions",
        sa.Column("initial_asset_ratings", sa.JSON(), nullable=True),
    )
    op.add_column(
        "ranking_sessions",
        sa.Column("skipped_pairs", sa.JSON(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("ranking_sessions", "skipped_pairs")
    op.drop_column("ranking_sessions", "initial_asset_ratings")
