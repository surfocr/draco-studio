"""Persist ranking session scope and selection strategy.

Revision ID: 0004_ranking_session_scope
Revises: 0003_job_runs
Create Date: 2026-04-06
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "0004_ranking_session_scope"
down_revision = "0003_job_runs"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "ranking_sessions",
        sa.Column("asset_scope", sa.String(length=32), nullable=False, server_default="all"),
    )
    op.add_column(
        "ranking_sessions",
        sa.Column(
            "selection_strategy",
            sa.String(length=32),
            nullable=False,
            server_default="uncertainty",
        ),
    )
    op.add_column(
        "ranking_sessions",
        sa.Column("asset_ids", sa.JSON(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("ranking_sessions", "asset_ids")
    op.drop_column("ranking_sessions", "selection_strategy")
    op.drop_column("ranking_sessions", "asset_scope")
