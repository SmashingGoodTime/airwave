"""Initial application schema.

Revision ID: 0001_initial_schema
Revises:
Create Date: 2026-04-27
"""

from __future__ import annotations

from alembic import op
from sqlalchemy import Column
from sqlalchemy import inspect

from server.database import Base
import server.models  # noqa: F401 - load model metadata


revision = "0001_initial_schema"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Create the current schema and repair legacy pre-Alembic tables."""
    bind = op.get_bind()

    # New installations get the full schema. Existing installations keep
    # their data because SQLAlchemy uses CREATE TABLE IF NOT EXISTS here.
    Base.metadata.create_all(bind=bind, checkfirst=True)

    # Databases created before Alembic may have tables that predate newer
    # columns. Add any simple missing columns from the current model metadata.
    inspector = inspect(bind)
    for table in Base.metadata.sorted_tables:
        if not inspector.has_table(table.name):
            continue

        existing_columns = {
            column["name"] for column in inspector.get_columns(table.name)
        }
        for column in table.columns:
            if column.name in existing_columns:
                continue
            op.add_column(
                table.name,
                Column(
                    column.name,
                    column.type,
                    nullable=column.nullable,
                    server_default=column.server_default,
                ),
            )

        # Refresh inspector state after potential ALTER TABLE statements.
        inspector = inspect(bind)


def downgrade() -> None:
    """Drop all application tables."""
    bind = op.get_bind()
    Base.metadata.drop_all(bind=bind, checkfirst=True)
