"""Tests for mirroring generated content into the program timeline."""

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

import pytest

from server.engine.timeline_mirror import (
    mirror_dj_break_ready,
    mirror_track_ready,
)
from server.models.audio_asset import AudioAsset
from server.models.dj_break import DJBreak
from server.models.program_item import ProgramItem
from server.models.track import Track


@pytest.mark.asyncio
async def test_mirror_track_ready_creates_asset_and_program_item(
    db_session: AsyncSession,
):
    track = Track(
        filepath="audio/tracks/song.wav",
        title="Mirror Song",
        duration=123.4,
        loudness_lufs=-14.0,
        provider="mock_music",
        status="ready",
        metadata_json='{"mood": "bright"}',
    )
    db_session.add(track)
    await db_session.commit()
    await db_session.refresh(track)

    item = await mirror_track_ready(db_session, track)
    await db_session.commit()
    await db_session.refresh(item)

    asset = await db_session.get(AudioAsset, item.audio_asset_id)
    assert asset is not None
    assert asset.asset_type == "music_track"
    assert asset.normalized_filepath == "audio/tracks/song.wav"
    assert asset.duration == 123.4
    assert asset.loudness_lufs == -14.0
    assert asset.provider == "mock_music"

    assert item.item_type == "music_track"
    assert item.status == "ready"
    assert item.source_table == "tracks"
    assert item.source_id == track.id
    assert item.title == "Mirror Song"
    assert item.duration == 123.4
    assert item.metadata_json == track.metadata_json


@pytest.mark.asyncio
async def test_mirror_track_ready_is_idempotent(db_session: AsyncSession):
    track = Track(filepath="audio/tracks/song.wav", title="Mirror Song", status="ready")
    db_session.add(track)
    await db_session.commit()
    await db_session.refresh(track)

    first = await mirror_track_ready(db_session, track)
    second = await mirror_track_ready(db_session, track)
    await db_session.commit()

    count = await db_session.scalar(
        select(func.count(ProgramItem.id)).where(
            ProgramItem.source_table == "tracks",
            ProgramItem.source_id == track.id,
        )
    )
    assert first.id == second.id
    assert count == 1


@pytest.mark.asyncio
async def test_mirror_dj_break_ready_creates_speech_asset(db_session: AsyncSession):
    dj_break = DJBreak(
        audio_filepath="audio/breaks/break.wav",
        script_text="Hello listeners",
        duration=15.0,
        status="ready",
        context='{"station": "Test"}',
    )
    db_session.add(dj_break)
    await db_session.commit()
    await db_session.refresh(dj_break)

    item = await mirror_dj_break_ready(db_session, dj_break)
    await db_session.commit()
    await db_session.refresh(item)

    asset = await db_session.get(AudioAsset, item.audio_asset_id)
    assert asset is not None
    assert asset.asset_type == "dj_break"
    assert asset.normalized_filepath == "audio/breaks/break.wav"
    assert item.item_type == "dj_break"
    assert item.source_table == "dj_breaks"
    assert item.source_id == dj_break.id
    assert item.duration == 15.0
    assert item.metadata_json == dj_break.context
