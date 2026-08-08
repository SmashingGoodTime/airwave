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
        assert not tables & {"talk_show_configs", "talk_topics", "talk_segments"}
        assert station_count == 1
        assert version == "0005_track_queued_at"
    finally:
        if database._engine is not None:
            await database._engine.dispose()
        database._engine = None
        database._async_session = None


@pytest.mark.asyncio
async def test_migration_drops_existing_talk_show_schema(monkeypatch, tmp_path):
    """An installation that ran talk shows should have that schema removed."""
    from server.config import settings
    import server.database as database

    db_path = tmp_path / "with_talk.db"
    engine = create_async_engine(sqlite_url(db_path), echo=False)
    async with engine.begin() as conn:
        await conn.execute(
            text(
                """
                CREATE TABLE talk_show_configs (
                    id INTEGER PRIMARY KEY,
                    name VARCHAR NOT NULL
                )
                """
            )
        )
        await conn.execute(
            text(
                """
                CREATE TABLE talk_topics (
                    id INTEGER PRIMARY KEY,
                    talk_config_id INTEGER NOT NULL,
                    title VARCHAR NOT NULL
                )
                """
            )
        )
        await conn.execute(
            text(
                """
                CREATE TABLE talk_segments (
                    id INTEGER PRIMARY KEY,
                    show_id INTEGER,
                    status VARCHAR
                )
                """
            )
        )
        # The foreign key matters: SQLite refuses to DROP COLUMN a column
        # named in one, which is how installations that ran talk shows are
        # shaped, so a fixture without it would not exercise the real path.
        await conn.execute(
            text(
                """
                CREATE TABLE shows (
                    id INTEGER PRIMARY KEY,
                    name VARCHAR NOT NULL,
                    show_type VARCHAR,
                    talk_config_id INTEGER,
                    FOREIGN KEY(talk_config_id)
                        REFERENCES talk_show_configs (id) ON DELETE SET NULL
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
            tables = await conn.run_sync(
                lambda sync_conn: set(inspect(sync_conn).get_table_names())
            )
            show_columns = await conn.run_sync(
                lambda sync_conn: {
                    col["name"] for col in inspect(sync_conn).get_columns("shows")
                }
            )

        assert not tables & {"talk_show_configs", "talk_topics", "talk_segments"}
        assert "show_type" not in show_columns
        assert "talk_config_id" not in show_columns
        assert "duration_minutes" in show_columns
    finally:
        if database._engine is not None:
            await database._engine.dispose()
        database._engine = None
        database._async_session = None


@pytest.mark.asyncio
async def test_migration_rebuild_keeps_show_data_and_history(monkeypatch, tmp_path):
    """Rebuilding ``shows`` must not cascade-delete rows that hang off it.

    SQLite rebuilds a table by dropping it, and with foreign keys enforced
    that drop cascades into ``show_styles``. Aired talk history has to
    survive too — only timeline rows that never went out are purged.
    """
    from server.config import settings
    from server.database import Base
    import server.database as database
    import server.models  # noqa: F401 - load model metadata

    db_path = tmp_path / "populated.db"
    engine = create_async_engine(sqlite_url(db_path), echo=False)
    async with engine.begin() as conn:
        # Every current table except ``shows``, which is hand-built below in
        # its pre-removal shape.
        await conn.run_sync(
            lambda sync_conn: Base.metadata.create_all(
                sync_conn,
                tables=[
                    table
                    for table in Base.metadata.sorted_tables
                    if table.name != "shows"
                ],
            )
        )
        await conn.execute(
            text(
                """
                CREATE TABLE talk_show_configs (
                    id INTEGER PRIMARY KEY,
                    name VARCHAR NOT NULL
                )
                """
            )
        )
        await conn.execute(
            text(
                """
                CREATE TABLE shows (
                    id INTEGER NOT NULL PRIMARY KEY,
                    name VARCHAR NOT NULL,
                    show_type VARCHAR,
                    active BOOLEAN,
                    duration_minutes INTEGER,
                    queue_order INTEGER,
                    talk_config_id INTEGER,
                    dj_config_id INTEGER,
                    created_at DATETIME,
                    updated_at DATETIME,
                    FOREIGN KEY(talk_config_id)
                        REFERENCES talk_show_configs (id) ON DELETE SET NULL,
                    FOREIGN KEY(dj_config_id)
                        REFERENCES dj_configs (id) ON DELETE SET NULL
                )
                """
            )
        )
        await conn.execute(
            text("INSERT INTO talk_show_configs (id, name) VALUES (1, 'Morning Talk')")
        )
        await conn.execute(
            text(
                "INSERT INTO shows (id, name, show_type, duration_minutes, "
                "talk_config_id) VALUES (1, 'Drivetime', 'hybrid', 45, 1)"
            )
        )
        # Core inserts so the models' Python-side column defaults apply.
        tables = Base.metadata.tables
        await conn.execute(
            tables["styles"].insert(), {"id": 1, "name": "Ambient", "prompt": "calm"}
        )
        await conn.execute(tables["show_styles"].insert(), {"show_id": 1, "style_id": 1})
        await conn.execute(
            tables["audio_assets"].insert(), {"id": 10, "asset_type": "talk"}
        )
        await conn.execute(
            tables["generation_jobs"].insert(),
            {"id": 1, "job_type": "talk_render", "output_asset_id": 10},
        )
        await conn.execute(
            tables["program_items"].insert(),
            [
                {
                    "id": 1,
                    "item_type": "talk",
                    "status": "planned",
                    "source_table": "talk_segments",
                    "source_id": 5,
                    "show_id": 1,
                    "audio_asset_id": 10,
                },
                {
                    "id": 2,
                    "item_type": "talk",
                    "status": "played",
                    "source_table": "talk_segments",
                    "source_id": 6,
                    "show_id": 1,
                    "audio_asset_id": None,
                },
                {
                    "id": 3,
                    "item_type": "track",
                    "status": "played",
                    "source_table": "tracks",
                    "source_id": 7,
                    "show_id": 1,
                    "audio_asset_id": None,
                },
            ],
        )
    await engine.dispose()

    monkeypatch.setattr(settings, "DATABASE_URL", sqlite_url(db_path))
    database._engine = None
    database._async_session = None

    try:
        await database.init_db()

        async with database.get_engine().connect() as conn:
            show_links = (await conn.execute(text("SELECT * FROM show_styles"))).all()
            item_ids = [
                row[0]
                for row in await conn.execute(
                    text("SELECT id FROM program_items ORDER BY id")
                )
            ]
            show_row = (
                await conn.execute(
                    text("SELECT name, duration_minutes FROM shows WHERE id = 1")
                )
            ).one()
            asset_count = await conn.scalar(text("SELECT count(*) FROM audio_assets"))
            job_asset = await conn.scalar(
                text("SELECT output_asset_id FROM generation_jobs WHERE id = 1")
            )
            shows_ddl = await conn.scalar(
                text("SELECT sql FROM sqlite_master WHERE name = 'shows'")
            )
            violations = (
                await conn.exec_driver_sql("PRAGMA foreign_key_check")
            ).fetchall()
            foreign_keys_on = await conn.scalar(text("PRAGMA foreign_keys"))

        # The rebuild kept the show, its style links, and its aired history.
        assert show_links == [(1, 1)]
        assert show_row == ("Drivetime", 45)
        assert item_ids == [2, 3]

        # The unaired talk item's audio went with it, and the job that made it
        # no longer points at a row that is gone.
        assert asset_count == 0
        assert job_asset is None

        # No trace of the talk foreign key, and enforcement is back on for the
        # connections the app will actually serve requests with.
        assert "talk_config_id" not in shows_ddl
        assert "dj_configs" in shows_ddl
        assert violations == []
        assert foreign_keys_on == 1
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
        assert "queued_at" in track_columns
        assert version == "0005_track_queued_at"
    finally:
        if database._engine is not None:
            await database._engine.dispose()
        database._engine = None
        database._async_session = None
