"""Tests for recording source playout lifecycle into program timeline rows."""

from datetime import datetime, timezone

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from server.engine.timeline_state import (
    mark_source_failed,
    mark_source_played,
    mark_source_playing,
)
from server.models.program_item import ProgramItem


@pytest.mark.asyncio
async def test_mark_source_playing_sets_status_and_start_timestamps(
    db_session: AsyncSession,
):
    item = ProgramItem(
        item_type="music_track",
        status="ready",
        source_table="tracks",
        source_id=1,
    )
    db_session.add(item)
    await db_session.commit()

    updated = await mark_source_playing(db_session, "tracks", 1)
    await db_session.commit()
    await db_session.refresh(item)

    assert updated is not None
    assert updated.id == item.id
    assert item.status == "playing"
    assert item.queued_at is not None
    assert item.started_at is not None


@pytest.mark.asyncio
async def test_mark_source_played_sets_status_and_end_timestamp(
    db_session: AsyncSession,
):
    item = ProgramItem(
        item_type="music_track",
        status="playing",
        source_table="tracks",
        source_id=2,
    )
    db_session.add(item)
    await db_session.commit()

    updated = await mark_source_played(db_session, "tracks", 2)
    await db_session.commit()
    await db_session.refresh(item)

    assert updated is not None
    assert item.status == "played"
    assert item.ended_at is not None


@pytest.mark.asyncio
async def test_mark_source_failed_sets_status_and_end_timestamp(
    db_session: AsyncSession,
):
    item = ProgramItem(
        item_type="music_track",
        status="ready",
        source_table="tracks",
        source_id=3,
    )
    db_session.add(item)
    await db_session.commit()

    updated = await mark_source_failed(db_session, "tracks", 3)
    await db_session.commit()
    await db_session.refresh(item)

    assert updated is not None
    assert item.status == "failed"
    assert item.ended_at is not None


@pytest.mark.asyncio
async def test_missing_source_returns_none(db_session: AsyncSession):
    assert await mark_source_playing(db_session, "tracks", 404) is None
    assert await mark_source_played(db_session, "tracks", 404) is None
    assert await mark_source_failed(db_session, "tracks", 404) is None


@pytest.mark.asyncio
async def test_played_item_is_not_moved_back_to_playing(
    db_session: AsyncSession,
):
    ended_at = datetime.now(timezone.utc).replace(tzinfo=None)
    item = ProgramItem(
        item_type="music_track",
        status="played",
        source_table="tracks",
        source_id=4,
        ended_at=ended_at,
    )
    db_session.add(item)
    await db_session.commit()

    updated = await mark_source_playing(db_session, "tracks", 4)
    await db_session.commit()
    await db_session.refresh(item)

    assert updated is not None
    assert item.status == "played"
    assert item.started_at is None
    assert item.ended_at == ended_at


@pytest.mark.asyncio
async def test_refresh_does_not_restore_utc_timezone_globally(
    db_session: AsyncSession,
):
    ended_at = datetime.now(timezone.utc).replace(tzinfo=None)
    item = ProgramItem(
        item_type="music_track",
        status="played",
        source_table="tracks",
        source_id=5,
        ended_at=ended_at,
    )
    db_session.add(item)
    await db_session.commit()

    await db_session.refresh(item)

    assert item.ended_at == ended_at
    assert item.ended_at.tzinfo is None
