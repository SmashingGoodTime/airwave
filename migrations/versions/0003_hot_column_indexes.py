"""Add indexes on hot query columns.

These columns back queries that run on every dashboard poll and on each
WebSocket client tick (Track.status, PlayLog.started_at), plus timeline
lookups (ProgramItem.status / source_table / source_id, GenerationJob.status).
On SQLite each was previously a full table scan.

Revision ID: 0003_hot_column_indexes
Revises: 0002_timeline_foundation
Create Date: 2026-07-02
"""

from __future__ import annotations

from alembic import op

revision = "0003_hot_column_indexes"
down_revision = "0002_timeline_foundation"
branch_labels = None
depends_on = None


# (index_name, table, column) — names match SQLAlchemy's ix_<table>_<column>
# convention so create_all on fresh databases and this migration agree.
INDEXES = (
    ("ix_tracks_status", "tracks", "status"),
    ("ix_tracks_style_id", "tracks", "style_id"),
    ("ix_play_logs_started_at", "play_logs", "started_at"),
    ("ix_program_items_status", "program_items", "status"),
    ("ix_program_items_source_table", "program_items", "source_table"),
    ("ix_program_items_source_id", "program_items", "source_id"),
    ("ix_generation_jobs_status", "generation_jobs", "status"),
)


def upgrade() -> None:
    """Create the hot-column indexes if they do not already exist."""
    bind = op.get_bind()
    for index_name, table, column in INDEXES:
        bind.exec_driver_sql(
            f'CREATE INDEX IF NOT EXISTS "{index_name}" ON "{table}" ("{column}")'
        )


def downgrade() -> None:
    """Drop the hot-column indexes."""
    bind = op.get_bind()
    for index_name, _table, _column in reversed(INDEXES):
        bind.exec_driver_sql(f'DROP INDEX IF EXISTS "{index_name}"')
