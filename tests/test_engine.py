"""Tests for engine modules: DJBrain, MusicBufferManager, AudioPipeline."""

import json
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import pytest_asyncio
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from server.models.announcement import Announcement
from server.models.audio_asset import AudioAsset
from server.models.dj_break import DJBreak
from server.models.dj_config import DJConfig
from server.models.generation_job import GenerationJob
from server.models.program_item import ProgramItem
from server.models.show import Show
from server.models.station import Station
from server.models.style import Style
from server.models.talk_show_config import TalkShowConfig
from server.models.talk_topic import TalkTopic
from server.models.track import Track

from tests.conftest import MockMusicProvider, MockScriptWriterProvider, MockVoiceProvider


# ---------------------------------------------------------------------------
# DJBrain tests
# ---------------------------------------------------------------------------


class TestDJBrain:
    def _make_brain(self):
        from server.engine.dj_brain import DJBrain

        return DJBrain()

    def test_track_played_increments(self):
        brain = self._make_brain()
        assert brain._tracks_since_break == 0
        brain.track_played()
        assert brain._tracks_since_break == 1
        brain.track_played()
        assert brain._tracks_since_break == 2

    def test_should_break_with_default_frequency(self):
        brain = self._make_brain()
        # With frequency=3 variance=0, should break after exactly 3 tracks
        for _ in range(2):
            brain.track_played()
            assert brain.should_break(break_frequency=3, variance=0) is False
        brain.track_played()
        assert brain.should_break(break_frequency=3, variance=0) is True

    def test_reset_break_counter(self):
        brain = self._make_brain()
        brain.track_played()
        brain.track_played()
        brain.track_played()
        brain.reset_break_counter()
        assert brain._tracks_since_break == 0
        assert brain._next_break_at is None

    def test_should_break_respects_minimum(self):
        brain = self._make_brain()
        # Even with frequency=1, variance=5 could go negative, but min is 1
        brain.track_played()
        # should_break with freq=1 variance=0 => break after 1
        assert brain.should_break(break_frequency=1, variance=0) is True

    @pytest.mark.asyncio
    async def test_build_context(self, db_session):
        brain = self._make_brain()

        # Insert station and DJ config
        station = Station(timezone="UTC", setup_complete=True)
        dj_config = DJConfig(
            station_name="Test FM",
            dj_name="TestDJ",
            personality_prompt="Be cool",
            break_frequency=3,
            mention_time=True,
        )
        db_session.add(station)
        db_session.add(dj_config)
        await db_session.commit()

        context = await brain._build_context(db_session)
        assert context["station_name"] == "Test FM"
        assert context["dj_name"] == "TestDJ"
        assert context["mention_time"] is True
        assert "recent_tracks" in context
        assert "announcements" in context
        assert "current_time" in context

    @pytest.mark.asyncio
    async def test_build_context_with_tracks(self, db_session):
        brain = self._make_brain()

        # Insert some played tracks
        for i in range(3):
            track = Track(
                title=f"Song {i}",
                style_prompt=f"style {i}",
                status="played",
                played_at=datetime.now(timezone.utc),
            )
            db_session.add(track)
        await db_session.commit()

        context = await brain._build_context(db_session)
        assert len(context["recent_tracks"]) == 3

    @pytest.mark.asyncio
    async def test_build_context_with_announcements(self, db_session):
        brain = self._make_brain()

        # Active announcement
        ann = Announcement(text="Concert tonight!", priority="high", active=True)
        db_session.add(ann)
        # Expired announcement (still active flag but expired)
        expired = Announcement(
            text="Old news",
            priority="normal",
            active=True,
            expires_at=datetime(2020, 1, 1, tzinfo=timezone.utc),
        )
        db_session.add(expired)
        await db_session.commit()

        context = await brain._build_context(db_session)
        # Only the non-expired announcement should appear
        active_texts = [a["text"] for a in context["announcements"]]
        assert "Concert tonight!" in active_texts
        assert "Old news" not in active_texts

    @pytest.mark.asyncio
    async def test_build_context_respects_max_plays(self, db_session):
        brain = self._make_brain()

        ann = Announcement(
            text="Limited announcement",
            priority="normal",
            active=True,
            max_plays=2,
            play_count=2,
        )
        db_session.add(ann)
        await db_session.commit()

        context = await brain._build_context(db_session)
        texts = [a["text"] for a in context["announcements"]]
        assert "Limited announcement" not in texts

    @pytest.mark.asyncio
    async def test_get_voice_config_defaults(self, db_session):
        brain = self._make_brain()
        config = await brain._get_voice_config(db_session)
        assert "voice_id" in config

    @pytest.mark.asyncio
    async def test_get_voice_config_from_db(self, db_session):
        brain = self._make_brain()
        dj_config = DJConfig(voice_id="custom_voice", voice_settings='{"stability": 0.5}')
        db_session.add(dj_config)
        await db_session.commit()

        config = await brain._get_voice_config(db_session)
        assert config["voice_id"] == "custom_voice"
        assert config["stability"] == 0.5

    @pytest.mark.asyncio
    async def test_increment_announcement_plays(self, db_session):
        brain = self._make_brain()
        ann = Announcement(text="Test", priority="normal", active=True, play_count=0)
        db_session.add(ann)
        await db_session.commit()
        await db_session.refresh(ann)

        await brain.increment_announcement_plays(db_session, [ann.id])
        await db_session.refresh(ann)
        assert ann.play_count == 1

    @pytest.mark.asyncio
    async def test_generate_break_no_scriptwriter(self, db_session):
        brain = self._make_brain()
        # No providers configured => None registry
        with patch(
            "server.engine.dj_brain.ProviderRegistry.get_instance"
        ) as mock_reg:
            reg = MagicMock()
            reg.get_scriptwriter_provider.return_value = None
            mock_reg.return_value = reg
            result = await brain.generate_break(db_session)
            assert result is None

    @pytest.mark.asyncio
    async def test_generate_break_mirrors_timeline(
        self, db_session, mock_scriptwriter_provider, mock_voice_provider
    ):
        brain = self._make_brain()
        brain._pipeline.process = AsyncMock(
            return_value={
                "processed_path": "audio/breaks/generated.wav",
                "duration": 12.0,
                "loudness_lufs": -14.0,
            }
        )

        with patch(
            "server.engine.dj_brain.ProviderRegistry.get_instance"
        ) as mock_reg:
            reg = MagicMock()
            reg.get_scriptwriter_provider.return_value = mock_scriptwriter_provider
            reg.get_voice_provider.return_value = mock_voice_provider
            mock_reg.return_value = reg

            dj_break = await brain.generate_break(db_session)

        assert dj_break is not None
        result = await db_session.execute(
            select(ProgramItem).where(
                ProgramItem.source_table == "dj_breaks",
                ProgramItem.source_id == dj_break.id,
            )
        )
        item = result.scalar_one()
        asset = await db_session.get(AudioAsset, item.audio_asset_id)

        assert item.item_type == "dj_break"
        assert item.status == "ready"
        assert asset is not None
        assert asset.normalized_filepath == "audio/breaks/generated.wav"

        job = (
            await db_session.execute(
                select(GenerationJob).where(
                    GenerationJob.job_type == "generate_dj_break"
                )
            )
        ).scalar_one()
        assert job.status == "succeeded"
        assert job.capability == "write_dj_break"
        assert job.output_asset_id == asset.id

    @pytest.mark.asyncio
    async def test_generate_break_records_failed_generation_job(self, db_session):
        brain = self._make_brain()
        scriptwriter = MagicMock()
        scriptwriter.write_break = AsyncMock(side_effect=RuntimeError("script down"))

        with patch(
            "server.engine.dj_brain.ProviderRegistry.get_instance"
        ) as mock_reg:
            reg = MagicMock()
            reg.get_scriptwriter_provider.return_value = scriptwriter
            reg.get_voice_provider.return_value = None
            mock_reg.return_value = reg

            result = await brain.generate_break(db_session)

        assert result is None
        job = (
            await db_session.execute(
                select(GenerationJob).where(
                    GenerationJob.job_type == "generate_dj_break"
                )
            )
        ).scalar_one()
        assert job.status == "failed"
        assert job.error_message == "script down"


# ---------------------------------------------------------------------------
# MusicBufferManager tests
# ---------------------------------------------------------------------------


class TestMusicBufferManager:
    def _make_manager(self):
        from server.engine.music_buffer import MusicBufferManager

        return MusicBufferManager()

    @pytest.mark.asyncio
    async def test_get_buffer_depth_empty(self, db_session):
        mgr = self._make_manager()
        depth = await mgr.get_buffer_depth(db_session)
        assert depth == 0

    @pytest.mark.asyncio
    async def test_get_buffer_depth_with_tracks(self, db_session):
        mgr = self._make_manager()
        for _ in range(3):
            db_session.add(Track(status="ready", title="t"))
        db_session.add(Track(status="played", title="t"))  # Not counted
        await db_session.commit()

        depth = await mgr.get_buffer_depth(db_session)
        assert depth == 3

    @pytest.mark.asyncio
    async def test_select_style_no_styles(self, db_session):
        mgr = self._make_manager()
        style = await mgr._select_style(db_session)
        assert style is None

    @pytest.mark.asyncio
    async def test_select_style_single(self, db_session):
        mgr = self._make_manager()
        db_session.add(Style(name="Ambient", prompt="ambient music", active=True, weight=1.0))
        await db_session.commit()

        style = await mgr._select_style(db_session)
        assert style is not None
        assert style.name == "Ambient"

    @pytest.mark.asyncio
    async def test_select_style_respects_active(self, db_session):
        mgr = self._make_manager()
        db_session.add(Style(name="Active", prompt="p1", active=True, weight=1.0))
        db_session.add(Style(name="Inactive", prompt="p2", active=False, weight=1.0))
        await db_session.commit()

        # Run many selections — should never get inactive
        names = set()
        for _ in range(20):
            s = await mgr._select_style(db_session)
            if s:
                names.add(s.name)
        assert "Active" in names
        assert "Inactive" not in names

    @pytest.mark.asyncio
    async def test_select_style_avoids_back_to_back(self, db_session):
        mgr = self._make_manager()
        s1 = Style(name="A", prompt="p1", active=True, weight=1.0)
        s2 = Style(name="B", prompt="p2", active=True, weight=1.0)
        db_session.add(s1)
        db_session.add(s2)
        await db_session.commit()
        await db_session.refresh(s1)

        # Create a track with style A as the most recent
        track = Track(title="t", style_id=s1.id, status="ready")
        db_session.add(track)
        await db_session.commit()

        # With two styles and last was A, selection should prefer B
        selections = set()
        for _ in range(20):
            s = await mgr._select_style(db_session)
            if s:
                selections.add(s.name)
        assert "B" in selections

    @pytest.mark.asyncio
    async def test_select_style_time_schedule(self, db_session):
        mgr = self._make_manager()
        now_hour = datetime.now(timezone.utc).hour
        # Create style with a schedule that includes current hour
        schedule = json.dumps({"start": f"{now_hour:02d}:00", "end": f"{now_hour:02d}:59"})
        db_session.add(
            Style(name="Scheduled", prompt="p", active=True, weight=1.0, schedule=schedule)
        )
        await db_session.commit()

        style = await mgr._select_style(db_session)
        assert style is not None
        assert style.name == "Scheduled"

    @pytest.mark.asyncio
    async def test_check_and_fill_skips_when_generating(self, db_session):
        mgr = self._make_manager()
        mgr._generating = True
        # Should return immediately without error
        await mgr.check_and_fill(db_session)

    @pytest.mark.asyncio
    async def test_check_and_fill_no_provider(self, db_session):
        mgr = self._make_manager()
        station = Station(buffer_target=5, buffer_warning_threshold=2)
        db_session.add(station)
        db_session.add(Style(name="X", prompt="p", active=True, weight=1.0))
        await db_session.commit()

        # With no provider configured, should not crash
        with patch(
            "server.engine.music_buffer.ProviderRegistry.get_instance"
        ) as mock_reg:
            reg = MagicMock()
            reg.get_music_provider.return_value = None
            mock_reg.return_value = reg
            await mgr.check_and_fill(db_session)

    @pytest.mark.asyncio
    async def test_generate_track_mirrors_timeline(
        self, db_session, mock_music_provider
    ):
        mgr = self._make_manager()
        mgr._pipeline.process = AsyncMock(
            return_value={
                "processed_path": "audio/tracks/generated.wav",
                "duration": 180.0,
                "loudness_lufs": -14.0,
            }
        )
        db_session.add(Style(name="X", prompt="p", active=True, weight=1.0))
        await db_session.commit()

        with patch(
            "server.engine.music_buffer.ProviderRegistry.get_instance"
        ) as mock_reg:
            reg = MagicMock()
            reg.get_music_provider.return_value = mock_music_provider
            reg.get_scriptwriter_provider.return_value = None
            mock_reg.return_value = reg

            await mgr._generate_track(db_session)

        track = (
            await db_session.execute(select(Track).where(Track.status == "ready"))
        ).scalar_one()
        item = (
            await db_session.execute(
                select(ProgramItem).where(
                    ProgramItem.source_table == "tracks",
                    ProgramItem.source_id == track.id,
                )
            )
        ).scalar_one()
        asset = await db_session.get(AudioAsset, item.audio_asset_id)

        assert item.item_type == "music_track"
        assert item.title == track.title
        assert asset is not None
        assert asset.normalized_filepath == "audio/tracks/generated.wav"

        job = (
            await db_session.execute(
                select(GenerationJob).where(
                    GenerationJob.job_type == "generate_track"
                )
            )
        ).scalar_one()
        assert job.status == "succeeded"
        assert job.capability == "generate_music"
        assert job.output_asset_id == asset.id

    @pytest.mark.asyncio
    async def test_generate_track_records_failed_generation_job(
        self, db_session, failing_music_provider
    ):
        mgr = self._make_manager()
        db_session.add(Style(name="X", prompt="p", active=True, weight=1.0))
        await db_session.commit()

        with patch(
            "server.engine.music_buffer.ProviderRegistry.get_instance"
        ) as mock_reg:
            reg = MagicMock()
            reg.get_music_provider.return_value = failing_music_provider
            reg.get_scriptwriter_provider.return_value = None
            mock_reg.return_value = reg

            await mgr._generate_track(db_session)

        job = (
            await db_session.execute(
                select(GenerationJob).where(
                    GenerationJob.job_type == "generate_track"
                )
            )
        ).scalar_one()
        track = (await db_session.execute(select(Track))).scalar_one()

        assert job.status == "failed"
        assert job.error_message == "Provider unavailable"
        assert track.status == "failed"


class TestTalkShowEngine:
    def _make_engine(self):
        from server.engine.talk_show import TalkShowEngine

        return TalkShowEngine()

    @pytest.mark.asyncio
    async def test_generate_segment_mirrors_timeline(
        self, db_session, mock_voice_provider
    ):
        engine = self._make_engine()
        engine._pipeline.process = AsyncMock(
            return_value={
                "processed_path": "audio/talks/generated.wav",
                "duration": 60.0,
                "loudness_lufs": -13.8,
            }
        )
        config = TalkShowConfig(name="Morning Talk", host_voice_id="voice_1")
        db_session.add(config)
        await db_session.flush()
        show = Show(name="Morning", show_type="talk", talk_config_id=config.id)
        topic = TalkTopic(
            talk_config_id=config.id,
            title="AI News",
            prompt="Discuss AI news.",
            topic_type="monologue",
        )
        db_session.add_all([show, topic])
        await db_session.commit()
        await db_session.refresh(show)

        scriptwriter = MagicMock()
        scriptwriter.write_talk_segment = AsyncMock(
            return_value={
                "script_text": "A short talk segment.",
                "speakers": ["Host"],
            }
        )
        with patch(
            "server.engine.talk_show.ProviderRegistry.get_instance"
        ) as mock_reg:
            reg = MagicMock()
            reg.get_scriptwriter_provider.return_value = scriptwriter
            reg.get_voice_provider.return_value = mock_voice_provider
            mock_reg.return_value = reg

            segment = await engine.generate_segment(db_session, show)

        assert segment is not None
        item = (
            await db_session.execute(
                select(ProgramItem).where(
                    ProgramItem.source_table == "talk_segments",
                    ProgramItem.source_id == segment.id,
                )
            )
        ).scalar_one()
        asset = await db_session.get(AudioAsset, item.audio_asset_id)

        assert item.item_type == "talk_segment"
        assert item.title == "monologue"
        assert asset is not None
        assert asset.normalized_filepath == "audio/talks/generated.wav"

        job = (
            await db_session.execute(
                select(GenerationJob).where(
                    GenerationJob.job_type == "generate_talk_segment"
                )
            )
        ).scalar_one()
        assert job.status == "succeeded"
        assert job.capability == "write_talk_segment"
        assert job.output_asset_id == asset.id

    @pytest.mark.asyncio
    async def test_generate_segment_records_failed_generation_job(self, db_session):
        engine = self._make_engine()
        config = TalkShowConfig(name="Morning Talk", host_voice_id="voice_1")
        db_session.add(config)
        await db_session.flush()
        show = Show(name="Morning", show_type="talk", talk_config_id=config.id)
        topic = TalkTopic(
            talk_config_id=config.id,
            title="AI News",
            prompt="Discuss AI news.",
            topic_type="monologue",
        )
        db_session.add_all([show, topic])
        await db_session.commit()
        await db_session.refresh(show)

        scriptwriter = MagicMock()
        scriptwriter.write_talk_segment = AsyncMock(side_effect=RuntimeError("talk down"))
        with patch(
            "server.engine.talk_show.ProviderRegistry.get_instance"
        ) as mock_reg:
            reg = MagicMock()
            reg.get_scriptwriter_provider.return_value = scriptwriter
            reg.get_voice_provider.return_value = None
            mock_reg.return_value = reg

            segment = await engine.generate_segment(db_session, show)

        assert segment is None
        job = (
            await db_session.execute(
                select(GenerationJob).where(
                    GenerationJob.job_type == "generate_talk_segment"
                )
            )
        ).scalar_one()
        assert job.status == "failed"
        assert job.error_message == "talk down"


# ---------------------------------------------------------------------------
# AudioPipeline tests
# ---------------------------------------------------------------------------


class TestAudioPipeline:
    def _make_pipeline(self):
        from server.engine.audio_pipeline import AudioPipeline

        return AudioPipeline()

    def test_default_target_lufs(self):
        pipeline = self._make_pipeline()
        assert pipeline._target_lufs == -14.0

    def test_custom_target_lufs(self):
        from server.engine.audio_pipeline import AudioPipeline

        pipeline = AudioPipeline(target_lufs=-16.0)
        assert pipeline._target_lufs == -16.0

    @pytest.mark.asyncio
    async def test_convert_format_unsupported(self):
        pipeline = self._make_pipeline()
        result = await pipeline.convert_format("/some/file.ogg", "flac")
        assert result == "/some/file.ogg"  # Returns original for unsupported
