"""Remove the talk show feature.

Drops the three talk-show tables and the ``shows`` columns that only
existed to point a program block at a talk config. Timeline mirror rows
for talk segments that never aired are removed too — their source table
is gone, so they could only ever show up in the dashboard as dangling
entries. Aired history is preserved: ``play_logs`` rows and already
played/failed timeline items are left alone, because stations need the
airtime record for compliance.

Generated talk audio under ``audio/talks/`` is left on disk; nothing
sweeps that directory any more, so it can be deleted by hand.

Revision ID: 0004_remove_talk_shows
Revises: 0003_hot_column_indexes
Create Date: 2026-08-04
"""

from __future__ import annotations

from alembic import op
from sqlalchemy import inspect

revision = "0004_remove_talk_shows"
down_revision = "0003_hot_column_indexes"
branch_labels = None
depends_on = None


# Child tables first so foreign keys stay satisfied while dropping.
TALK_TABLES = ("talk_segments", "talk_topics", "talk_show_configs")
SHOW_COLUMNS = ("show_type", "talk_config_id")

# Statuses that mean "has not aired yet" — safe to purge.
UNAIRED_STATUSES = ("planned", "ready", "queued", "playing")


def upgrade() -> None:
    """Drop talk-show tables, show columns, and unaired talk timeline rows."""
    bind = op.get_bind()

    placeholders = ", ".join(f"'{status}'" for status in UNAIRED_STATUSES)
    bind.exec_driver_sql(
        "DELETE FROM audio_assets WHERE id IN ("
        "  SELECT audio_asset_id FROM program_items"
        "  WHERE source_table = 'talk_segments'"
        f"    AND status IN ({placeholders})"
        "    AND audio_asset_id IS NOT NULL"
        ")"
    )
    bind.exec_driver_sql(
        "DELETE FROM program_items "
        "WHERE source_table = 'talk_segments' "
        f"  AND status IN ({placeholders})"
    )

    inspector = inspect(bind)
    for table_name in TALK_TABLES:
        if inspector.has_table(table_name):
            op.drop_table(table_name)

    # SQLite rewrites the table for each DROP COLUMN, so only touch the
    # columns that are actually still there.
    existing = {column["name"] for column in inspector.get_columns("shows")}
    for column_name in SHOW_COLUMNS:
        if column_name in existing:
            op.drop_column("shows", column_name)


def downgrade() -> None:
    """Recreate the show columns as empty placeholders.

    The talk-show tables and their data are not restored — the models
    that defined them no longer exist.
    """
    import sqlalchemy as sa

    bind = op.get_bind()
    existing = {column["name"] for column in inspect(bind).get_columns("shows")}
    if "show_type" not in existing:
        op.add_column(
            "shows",
            sa.Column("show_type", sa.String(), server_default="music"),
        )
    if "talk_config_id" not in existing:
        op.add_column("shows", sa.Column("talk_config_id", sa.Integer()))
