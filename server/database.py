"""Async SQLAlchemy database configuration and session management."""

from collections.abc import AsyncGenerator
from pathlib import Path
from typing import Optional

from alembic import command
from alembic.config import Config
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    """Base class for all SQLAlchemy ORM models."""

    pass


_engine: Optional[AsyncEngine] = None
_async_session: Optional[async_sessionmaker[AsyncSession]] = None


def get_engine() -> AsyncEngine:
    """Get or create the async SQLAlchemy engine."""
    global _engine
    if _engine is None:
        from server.config import settings

        _engine = create_async_engine(settings.DATABASE_URL, echo=False)
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
    """Upgrade the configured database to the latest Alembic revision."""

    def _upgrade(sync_connection) -> None:
        config = get_alembic_config()
        config.attributes["connection"] = sync_connection
        command.upgrade(config, "head")

    async with get_engine().begin() as conn:
        await conn.run_sync(_upgrade)


async def init_db() -> None:
    """Run migrations and ensure singleton defaults exist.

    If no Station row is present after migration, one is inserted with
    ``setup_complete=True`` so the first-run wizard is skipped.
    """
    import server.models  # noqa: F401 - ensure models are loaded

    await run_migrations()

    # Ensure a default Station record exists so the setup wizard is skipped.
    from sqlalchemy import select
    from server.models.station import Station

    async with get_session_factory()() as session:
        result = await session.execute(select(Station).limit(1))
        if result.scalar_one_or_none() is None:
            session.add(Station(setup_complete=True))
            await session.commit()

    # Ensure the first DJConfig row (if any) is marked as default.
    from server.models.dj_config import DJConfig

    async with get_session_factory()() as session:
        result = await session.execute(select(DJConfig))
        configs = list(result.scalars().all())
        if configs and not any(c.is_default for c in configs):
            configs[0].is_default = True
            await session.commit()


async def get_session() -> AsyncGenerator[AsyncSession, None]:
    """Yield an async database session for use as a FastAPI dependency."""
    factory = get_session_factory()
    async with factory() as session:
        yield session
