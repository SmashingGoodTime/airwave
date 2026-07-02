"""Helpers for recording source playout state into timeline mirror rows."""

from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from server.models.program_item import ProgramItem


async def mark_source_playing(
    session: AsyncSession,
    source_table: str,
    source_id: int,
) -> ProgramItem | None:
    """Mark an existing mirrored source item as queued and playing.

    Args:
        session: Async database session.
        source_table: Legacy source table name such as "tracks".
        source_id: Legacy source primary key.

    Returns:
        The updated program item, or None if no mirror row exists.
    """
    item = await _get_source_item(session, source_table, source_id)
    if item is None:
        return None
    if item.status == "played":
        return item

    now = _now()
    item.status = "playing"
    if item.queued_at is None:
        item.queued_at = now
    if item.started_at is None:
        item.started_at = now
    await session.flush()
    return item


async def mark_source_played(
    session: AsyncSession,
    source_table: str,
    source_id: int,
) -> ProgramItem | None:
    """Mark an existing mirrored source item as played."""
    item = await _get_source_item(session, source_table, source_id)
    if item is None:
        return None

    item.status = "played"
    if item.ended_at is None:
        item.ended_at = _now()
    await session.flush()
    return item


async def mark_source_failed(
    session: AsyncSession,
    source_table: str,
    source_id: int,
) -> ProgramItem | None:
    """Mark an existing mirrored source item as failed."""
    item = await _get_source_item(session, source_table, source_id)
    if item is None:
        return None

    item.status = "failed"
    if item.ended_at is None:
        item.ended_at = _now()
    await session.flush()
    return item


async def _get_source_item(
    session: AsyncSession,
    source_table: str,
    source_id: int,
) -> ProgramItem | None:
    """Return the timeline row for a legacy source record if it exists."""
    result = await session.execute(
        select(ProgramItem).where(
            ProgramItem.source_table == source_table,
            ProgramItem.source_id == source_id,
        )
    )
    return result.scalar_one_or_none()


def _now() -> datetime:
    """Return the current UTC timestamp."""
    return datetime.now(timezone.utc)
