"""Add tracks.queued_at for orphaned-queue detection.

Cleanup previously keyed the stale-"queued" reset on ``created_at``, which
is generation time — prefilled tracks can be arbitrarily old when queued,
so legitimately queued tracks were reset to "ready" and aired twice. The
scheduler now stamps ``queued_at`` when it pushes a track to playout and
compares against that instead.

Revision ID: 0005_track_queued_at
Revises: 0004_remove_talk_shows
Create Date: 2026-08-07
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0005_track_queued_at"
down_revision = "0004_remove_talk_shows"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Add the queued_at column unless 0001's model-driven repair created it."""
    bind = op.get_bind()
    columns = {row[1] for row in bind.exec_driver_sql("PRAGMA table_info('tracks')")}
    if "queued_at" not in columns:
        op.add_column("tracks", sa.Column("queued_at", sa.DateTime(), nullable=True))


def downgrade() -> None:
    """Drop the queued_at column."""
    bind = op.get_bind()
    columns = {row[1] for row in bind.exec_driver_sql("PRAGMA table_info('tracks')")}
    if "queued_at" in columns:
        op.drop_column("tracks", "queued_at")
