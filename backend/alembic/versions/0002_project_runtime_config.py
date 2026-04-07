"""Add project runtime configuration table.

Revision ID: 0002_project_runtime_config
Revises: 0001_initial_schema
Create Date: 2026-04-06
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "0002_project_runtime_config"
down_revision = "0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "project_runtime_configs",
        sa.Column("project_id", sa.String(length=36), nullable=False),
        sa.Column("runtime_mode", sa.String(length=16), nullable=False, server_default="local"),
        sa.Column("task_provider_overrides", sa.JSON(), nullable=True),
        sa.Column("task_provider_options", sa.JSON(), nullable=True),
        sa.Column("benchmark_preferences", sa.JSON(), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("project_id"),
    )


def downgrade() -> None:
    op.drop_table("project_runtime_configs")
