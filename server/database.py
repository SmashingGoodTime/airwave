"""Async SQLAlchemy database configuration and session management."""

import logging
from collections.abc import AsyncGenerator
from pathlib import Path
from typing import Optional

from alembic import command
from alembic.config import Config
from sqlalchemy import event
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import DeclarativeBase


logger = logging.getLogger(__name__)


class Base(DeclarativeBase):
    """Base class for all SQLAlchemy ORM models."""

    pass


_engine: Optional[AsyncEngine] = None
_async_session: Optional[async_sessionmaker[AsyncSession]] = None


def _configure_sqlite_pragmas(dbapi_connection, connection_record) -> None:
    """Apply per-connection SQLite pragmas for concurrency and integrity.

    - ``journal_mode=WAL`` lets a writer and readers proceed concurrently.
    - ``busy_timeout`` makes a blocked connection wait rather than raising
      ``database is locked`` immediately.
    - ``foreign_keys=ON`` enforces the ``ondelete`` behaviour declared on the
      models (SQLite ignores foreign keys unless this is set per connection).
    """
    cursor = dbapi_connection.cursor()
    try:
        cursor.execute("PRAGMA journal_mode=WAL")
        cursor.execute("PRAGMA busy_timeout=5000")
        cursor.execute("PRAGMA foreign_keys=ON")
    finally:
        cursor.close()


def get_engine() -> AsyncEngine:
    """Get or create the async SQLAlchemy engine."""
    global _engine
    if _engine is None:
        from server.config import settings

        is_sqlite = settings.DATABASE_URL.startswith("sqlite")
        connect_args = {"timeout": 30} if is_sqlite else {}
        _engine = create_async_engine(
            settings.DATABASE_URL, echo=False, connect_args=connect_args
        )
        if is_sqlite:
            # aiosqlite exposes the underlying sqlite3 connection via the sync
            # engine; attach the pragma listener there.
            event.listen(
                _engine.sync_engine, "connect", _configure_sqlite_pragmas
            )
    return _engine


def get_session_factory() -> async_sessionmaker[AsyncSession]:
    """Get or create the async session factory."""
    global _async_session
    if _async_session is None:
        _async_session = async_sessionmaker(
            get_engine(), class_=AsyncSession, expire_on_commit=False
        )
    return _async_session


def get_alembic_config() -> Config:
    """Build Alembic config for programmatic migrations."""
    root_dir = Path(__file__).resolve().parent.parent
    config = Config(str(root_dir / "alembic.ini"))
    config.set_main_option("script_location", str(root_dir / "migrations"))
    return config


async def run_migrations() -> None:
    """Upgrade the configured database to the latest Alembic revision.

    SQLite cannot change a table's shape in place, so a migration that alters
    one rebuilds it: copy the rows out, ``DROP TABLE``, rename the copy back.
    With ``foreign_keys=ON`` that drop performs an implicit delete which fires
    ``ON DELETE CASCADE`` on child rows — rebuilding ``shows`` would silently
    wipe every show/style link. Enforcement is therefore off for the upgrade,
    and since ``PRAGMA foreign_keys`` is a no-op inside a transaction it has to
    be set before Alembic opens one. It is restored before the connection goes
    back to the pool, and the result is checked for orphans.
    """

    def _upgrade(sync_connection) -> None:
        config = get_alembic_config()
        config.attributes["connection"] = sync_connection
        command.upgrade(config, "head")

    engine = get_engine()
    is_sqlite = engine.dialect.name == "sqlite"

    async with engine.connect() as conn:
        if is_sqlite:
            await conn.exec_driver_sql("PRAGMA foreign_keys=OFF")
        try:
            await conn.run_sync(_upgrade)
        except Exception:
            await conn.rollback()
            raise
        else:
            await conn.commit()
        finally:
            if is_sqlite:
                await conn.exec_driver_sql("PRAGMA foreign_keys=ON")

    if is_sqlite:
        await _log_foreign_key_violations()


async def _log_foreign_key_violations() -> None:
    """Warn about rows left pointing at a missing parent after migrating.

    Migrations run without foreign key enforcement, so this is the check that
    would otherwise have happened as they went. Orphans are reported rather
    than raised on: a stale reference is not worth refusing to go on air over.
    """
    async with get_engine().connect() as conn:
        result = await conn.exec_driver_sql("PRAGMA foreign_key_check")
        violations = result.fetchall()

    if violations:
        tables = sorted({row[0] for row in violations})
        logger.warning(
            "Foreign key check found %d orphaned row(s) after migration in: %s",
            len(violations),
            ", ".join(tables),
        )


async def init_db() -> None:
    """Run migrations and ensure singleton defaults exist.

    If no Station row is present after migration, one is inserted with
    ``setup_complete=False`` so the first-run wizard is presented until the
    operator completes it.
    """
    import server.models  # noqa: F401 - ensure models are loaded

    await run_migrations()

    # Ensure a default Station record exists. It starts with
    # ``setup_complete=False`` so the first-run wizard gates the UI; the
    # wizard's /complete endpoint flips this on the same row.
    from sqlalchemy import select
    from server.models.station import Station

    async with get_session_factory()() as session:
        result = await session.execute(select(Station).order_by(Station.id).limit(1))
        if result.scalar_one_or_none() is None:
            session.add(Station(setup_complete=False))
            await session.commit()

    # Ensure the first DJConfig row (if any) is marked as default.
    from server.models.dj_config import DJConfig

    async with get_session_factory()() as session:
        result = await session.execute(select(DJConfig).order_by(DJConfig.id))
        configs = list(result.scalars().all())
        if configs and not any(c.is_default for c in configs):
            configs[0].is_default = True
            await session.commit()


async def get_session() -> AsyncGenerator[AsyncSession, None]:
    """Yield an async database session for use as a FastAPI dependency."""
    factory = get_session_factory()
    async with factory() as session:
        yield session
