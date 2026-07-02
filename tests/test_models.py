"""Tests for SQLAlchemy ORM models."""

from datetime import datetime, timezone

import pytest
import pytest_asyncio
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from server.models.announcement import Announcement
from server.models.audio_asset import AudioAsset
from server.models.dj_break import DJBreak
from server.models.dj_config import DJConfig
from server.models.generation_job import GenerationJob
from server.models.playlog import PlayLog
from server.models.program_item import ProgramItem
from server.models.station import Station
from server.models.style import Style
from server.models.track import Track


class TestTrackModel:
    @pytest.mark.asyncio
    async def test_create_track(self, db_session: AsyncSession):
        track = Track(title="Test Song", status="generating", provider="suno")
        db_session.add(track)
        await db_session.commit()
        await db_session.refresh(track)

        assert track.id is not None
        assert track.uuid is not None
        assert track.title == "Test Song"
        assert track.status == "generating"
        assert track.created_at is not None

    @pytest.mark.asyncio
    async def test_track_defaults(self, db_session: AsyncSession):
        track = Track()
        db_session.add(track)
        await db_session.commit()
        await db_session.refresh(track)

        assert track.status == "generating"
        assert track.filepath is None
        assert track.duration is None

    @pytest.mark.asyncio
    async def test_track_uuid_unique(self, db_session: AsyncSession):
        t1 = Track(title="A")
        t2 = Track(title="B")
        db_session.add_all([t1, t2])
        await db_session.commit()
        await db_session.refresh(t1)
        await db_session.refresh(t2)
        assert t1.uuid != t2.uuid


class TestStyleModel:
    @pytest.mark.asyncio
    async def test_create_style(self, db_session: AsyncSession):
        style = Style(name="Ambient", prompt="ambient electronic music")
        db_session.add(style)
        await db_session.commit()
        await db_session.refresh(style)

        assert style.id is not None
        assert style.name == "Ambient"
        assert style.active is True
        assert style.weight == 1.0
        assert style.created_at is not None

    @pytest.mark.asyncio
    async def test_style_with_schedule(self, db_session: AsyncSession):
        style = Style(
            name="Night",
            prompt="dark ambient",
            schedule='{"start": "22:00", "end": "06:00"}',
        )
        db_session.add(style)
        await db_session.commit()
        await db_session.refresh(style)
        assert style.schedule is not None


class TestAnnouncementModel:
    @pytest.mark.asyncio
    async def test_create_announcement(self, db_session: AsyncSession):
        ann = Announcement(text="Breaking news!", priority="urgent")
        db_session.add(ann)
        await db_session.commit()
        await db_session.refresh(ann)

        assert ann.id is not None
        assert ann.text == "Breaking news!"
        assert ann.priority == "urgent"
        assert ann.active is True
        assert ann.play_count == 0

    @pytest.mark.asyncio
    async def test_announcement_with_expiry(self, db_session: AsyncSession):
        # SQLite stores naive datetimes, so use naive for comparison
        expires = datetime(2030, 12, 31)
        ann = Announcement(text="Limited", expires_at=expires, max_plays=5)
        db_session.add(ann)
        await db_session.commit()
        await db_session.refresh(ann)

        assert ann.expires_at.year == 2030
        assert ann.expires_at.month == 12
        assert ann.max_plays == 5


class TestDJConfigModel:
    @pytest.mark.asyncio
    async def test_defaults(self, db_session: AsyncSession):
        config = DJConfig()
        db_session.add(config)
        await db_session.commit()
        await db_session.refresh(config)

        assert config.station_name == "AI Radio"
        assert config.dj_name == "DJ Claude"
        assert config.break_frequency == 3
        assert config.break_frequency_variance == 1
        assert config.mention_time is True
        assert config.content_policy == "clean_vocals"
        assert config.max_break_duration == 60


class TestDJBreakModel:
    @pytest.mark.asyncio
    async def test_create_break(self, db_session: AsyncSession):
        dj_break = DJBreak(
            script_text="Hey listeners!",
            status="ready",
            duration=15.5,
        )
        db_session.add(dj_break)
        await db_session.commit()
        await db_session.refresh(dj_break)

        assert dj_break.id is not None
        assert dj_break.script_text == "Hey listeners!"
        assert dj_break.duration == 15.5
        assert dj_break.status == "ready"


class TestPlayLogModel:
    @pytest.mark.asyncio
    async def test_create_playlog(self, db_session: AsyncSession):
        log = PlayLog(item_type="track", item_id=1, duration=180.0)
        db_session.add(log)
        await db_session.commit()
        await db_session.refresh(log)

        assert log.id is not None
        assert log.item_type == "track"
        assert log.started_at is not None


class TestAudioAssetModel:
    @pytest.mark.asyncio
    async def test_create_audio_asset(self, db_session: AsyncSession):
        asset = AudioAsset(
            asset_type="music_track",
            original_filepath="audio/raw/source.mp3",
            normalized_filepath="audio/tracks/track.wav",
            duration=180.5,
            loudness_lufs=-14.1,
            sample_rate=48000,
            channels=2,
            checksum="abc123",
            provider="suno",
        )
        db_session.add(asset)
        await db_session.commit()
        await db_session.refresh(asset)

        assert asset.id is not None
        assert asset.asset_type == "music_track"
        assert asset.status == "ready"
        assert asset.normalized_filepath == "audio/tracks/track.wav"
        assert asset.created_at is not None

    @pytest.mark.asyncio
    async def test_audio_asset_defaults(self, db_session: AsyncSession):
        asset = AudioAsset(asset_type="fallback")
        db_session.add(asset)
        await db_session.commit()
        await db_session.refresh(asset)

        assert asset.status == "ready"
        assert asset.normalized_filepath is None
        assert asset.duration is None


class TestProgramItemModel:
    @pytest.mark.asyncio
    async def test_create_program_item(self, db_session: AsyncSession):
        asset = AudioAsset(asset_type="dj_break", normalized_filepath="audio/breaks/1.wav")
        db_session.add(asset)
        await db_session.flush()

        item = ProgramItem(
            item_type="dj_break",
            audio_asset_id=asset.id,
            source_table="dj_breaks",
            source_id=1,
            title="Midday Break",
            position=10,
            duration=30.0,
        )
        db_session.add(item)
        await db_session.commit()
        await db_session.refresh(item)

        assert item.id is not None
        assert item.uuid is not None
        assert item.status == "planned"
        assert item.audio_asset_id == asset.id
        assert item.created_at is not None


class TestGenerationJobModel:
    @pytest.mark.asyncio
    async def test_create_generation_job(self, db_session: AsyncSession):
        job = GenerationJob(
            job_type="generate_track",
            capability="generate_music",
            provider="suno",
            input_json='{"prompt": "ambient"}',
            priority=5,
        )
        db_session.add(job)
        await db_session.commit()
        await db_session.refresh(job)

        assert job.id is not None
        assert job.uuid is not None
        assert job.status == "pending"
        assert job.attempts == 0
        assert job.max_attempts == 3
        assert job.created_at is not None


class TestStationModel:
    @pytest.mark.asyncio
    async def test_defaults(self, db_session: AsyncSession):
        station = Station()
        db_session.add(station)
        await db_session.commit()
        await db_session.refresh(station)

        assert station.timezone == "UTC"
        assert station.setup_complete is False
        assert station.buffer_target == 5
        assert station.buffer_warning_threshold == 2
        assert station.disk_retention_days == 30

    @pytest.mark.asyncio
    async def test_custom_values(self, db_session: AsyncSession):
        station = Station(
            timezone="US/Eastern",
            setup_complete=True,
            buffer_target=10,
        )
        db_session.add(station)
        await db_session.commit()
        await db_session.refresh(station)

        assert station.timezone == "US/Eastern"
        assert station.setup_complete is True
        assert station.buffer_target == 10
