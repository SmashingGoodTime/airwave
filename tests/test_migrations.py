"""Tests for Alembic database migrations."""

from pathlib import Path

import pytest
from sqlalchemy import inspect, text
from sqlalchemy.ext.asyncio import create_async_engine


def sqlite_url(path: Path) -> str:
    """Return a Windows-safe async SQLite URL."""
    return f"sqlite+aiosqlite:///{path.resolve().as_posix()}"


@pytest.mark.asyncio
async def test_init_db_runs_alembic_and_creates_defaults(monkeypatch, tmp_path):
    """init_db should upgrade a fresh database and create default Station."""
    from server.config import settings
    import server.database as database

    db_path = tmp_path / "fresh.db"
    monkeypatch.setattr(settings, "DATABASE_URL", sqlite_url(db_path))
    database._engine = None
    database._async_session = None

    try:
        await database.init_db()

        async with database.get_engine().begin() as conn:
            tables = await conn.run_sync(
                lambda sync_conn: set(inspect(sync_conn).get_table_names())
            )
            station_count = await conn.scalar(text("SELECT count(*) FROM stations"))
            version = await conn.scalar(text("SELECT version_num FROM alembic_version"))

        assert "alembic_version" in tables
        assert "tracks" in tables
        assert "shows" in tables
        assert "audio_assets" in tables
        assert "program_items" in tables
        assert "generation_jobs" in tables
        assert station_count == 1
        assert version == "0002_timeline_foundation"
    finally:
        if database._engine is not None:
            await database._engine.dispose()
        database._engine = None
        database._async_session = None


@pytest.mark.asyncio
async def test_initial_migration_repairs_legacy_missing_columns(monkeypatch, tmp_path):
    """The baseline migration should add known columns to legacy tables."""
    from server.config import settings
    import server.database as database

    db_path = tmp_path / "legacy.db"
    engine = create_async_engine(sqlite_url(db_path), echo=False)
    async with engine.begin() as conn:
        await conn.execute(
            text(
                """
                CREATE TABLE dj_configs (
                    id INTEGER PRIMARY KEY,
                    station_name VARCHAR,
                    dj_name VARCHAR
                )
                """
            )
        )
        await conn.execute(
            text(
                """
                CREATE TABLE shows (
                    id INTEGER PRIMARY KEY,
                    name VARCHAR NOT NULL,
                    start_time VARCHAR NOT NULL,
                    end_time VARCHAR NOT NULL
                )
                """
            )
        )
        await conn.execute(
            text(
                """
                CREATE TABLE tracks (
                    id INTEGER PRIMARY KEY,
                    title VARCHAR,
                    status VARCHAR
                )
                """
            )
        )
    await engine.dispose()

    monkeypatch.setattr(settings, "DATABASE_URL", sqlite_url(db_path))
    database._engine = None
    database._async_session = None

    try:
        await database.init_db()

        async with database.get_engine().begin() as conn:
            dj_columns = await conn.run_sync(
                lambda sync_conn: {
                    col["name"]
                    for col in inspect(sync_conn).get_columns("dj_configs")
                }
            )
            show_columns = await conn.run_sync(
                lambda sync_conn: {
                    col["name"]
                    for col in inspect(sync_conn).get_columns("shows")
                }
            )
            track_columns = await conn.run_sync(
                lambda sync_conn: {
                    col["name"]
                    for col in inspect(sync_conn).get_columns("tracks")
                }
            )
            version = await conn.scalar(text("SELECT version_num FROM alembic_version"))

        assert {"name", "is_default"}.issubset(dj_columns)
        assert "dj_config_id" in show_columns
        assert "lyrics" in track_columns
        assert version == "0002_timeline_foundation"
    finally:
        if database._engine is not None:
            await database._engine.dispose()
        database._engine = None
        database._async_session = None
