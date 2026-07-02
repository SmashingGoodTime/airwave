"""Add timeline foundation tables.

Revision ID: 0002_timeline_foundation
Revises: 0001_initial_schema
Create Date: 2026-06-12
"""

from __future__ import annotations

from alembic import op

from server.database import Base
import server.models  # noqa: F401 - load model metadata


revision = "0002_timeline_foundation"
down_revision = "0001_initial_schema"
branch_labels = None
depends_on = None


TIMELINE_TABLES = ("audio_assets", "program_items", "generation_jobs")


def upgrade() -> None:
    """Create the additive timeline foundation tables."""
    bind = op.get_bind()
    for table_name in TIMELINE_TABLES:
        Base.metadata.tables[table_name].create(bind=bind, checkfirst=True)


def downgrade() -> None:
    """Drop the additive timeline foundation tables."""
    bind = op.get_bind()
    for table_name in reversed(TIMELINE_TABLES):
        Base.metadata.tables[table_name].drop(bind=bind, checkfirst=True)
