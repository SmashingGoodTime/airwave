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

import sqlalchemy as sa
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

    _purge_unaired_talk_items(bind)

    # Rebuilding ``shows`` reflects it, and reflection has to be able to
    # resolve the talk foreign key, so this runs before the tables are gone.
    _drop_show_columns(bind)

    inspector = inspect(bind)
    for table_name in TALK_TABLES:
        if inspector.has_table(table_name):
            op.drop_table(table_name)


def _purge_unaired_talk_items(bind) -> None:
    """Delete timeline rows, and their audio, for talk segments that never aired."""
    statuses = ", ".join(f"'{status}'" for status in UNAIRED_STATUSES)
    unaired_talk = f"source_table = 'talk_segments' AND status IN ({statuses})"

    asset_ids = [
        row[0]
        for row in bind.exec_driver_sql(
            "SELECT audio_asset_id FROM program_items "
            f"WHERE {unaired_talk} AND audio_asset_id IS NOT NULL"
        )
    ]
    bind.exec_driver_sql(f"DELETE FROM program_items WHERE {unaired_talk}")

    if not asset_ids:
        return

    id_list = ", ".join(str(int(asset_id)) for asset_id in asset_ids)
    # Migrations run with foreign key enforcement off — SQLite cannot rebuild a
    # table with it on — so the ON DELETE SET NULL these assets would normally
    # trigger is applied by hand. Assets something else still points at are
    # left alone.
    bind.exec_driver_sql(
        f"DELETE FROM audio_assets WHERE id IN ({id_list}) AND id NOT IN "
        "(SELECT audio_asset_id FROM program_items WHERE audio_asset_id IS NOT NULL)"
    )
    bind.exec_driver_sql(
        "UPDATE generation_jobs SET output_asset_id = NULL "
        f"WHERE output_asset_id IN ({id_list}) "
        "AND output_asset_id NOT IN (SELECT id FROM audio_assets)"
    )


def _drop_show_columns(bind) -> None:
    """Rebuild ``shows`` without the columns that only served talk shows.

    SQLite refuses to DROP COLUMN a column named in a foreign key definition,
    and on installations whose ``shows`` table was created from the old models
    ``talk_config_id`` is exactly that. The table is rebuilt instead, with the
    dead foreign key left out of the new definition.
    """
    existing = {column["name"] for column in inspect(bind).get_columns("shows")}
    doomed = [name for name in SHOW_COLUMNS if name in existing]
    if not doomed:
        return

    shows = sa.Table("shows", sa.MetaData(), autoload_with=bind)
    for constraint in list(shows.constraints):
        if isinstance(constraint, sa.ForeignKeyConstraint) and any(
            column.name in doomed for column in constraint.columns
        ):
            shows.constraints.discard(constraint)
    for index in list(shows.indexes):
        if any(column.name in doomed for column in index.columns):
            shows.indexes.discard(index)

    with op.batch_alter_table("shows", copy_from=shows, recreate="always") as batch:
        for column_name in doomed:
            batch.drop_column(column_name)


def downgrade() -> None:
    """Recreate the show columns as empty placeholders.

    The talk-show tables and their data are not restored — the models
    that defined them no longer exist, so neither does the foreign key
    ``talk_config_id`` used to carry.
    """
    bind = op.get_bind()
    existing = {column["name"] for column in inspect(bind).get_columns("shows")}
    if "show_type" not in existing:
        op.add_column(
            "shows",
            sa.Column("show_type", sa.String(), server_default="music"),
        )
    if "talk_config_id" not in existing:
        op.add_column("shows", sa.Column("talk_config_id", sa.Integer()))
