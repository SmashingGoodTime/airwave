"""Reliability tests for scheduler playout and dead-air behavior."""

from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import AsyncMock

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from server.engine.scheduler import MasterScheduler
from server.models.dj_break import DJBreak
from server.models.dj_config import DJConfig
from server.models.playlog import PlayLog
from server.models.program_item import ProgramItem
from server.models.show import Show
from server.models.station import Station
from server.models.talk_segment import TalkSegment
from server.models.track import Track


class FakePlayout:
    """In-memory playout double for scheduler tests."""

    def __init__(self, queue_length: int = 0) -> None:
        self.queue_length = queue_length
        self.queued_tracks: list[str] = []
        self.queued_breaks: list[str] = []
        self.metadata_updates: list[tuple[str, str]] = []
        self.now_playing_file: str | None = None

    async def get_queue_length(self) -> int:
        """Return the configured queue length."""
        return self.queue_length

    async def wait_until_ready(
        self, timeout: float = 30.0, interval: float = 1.0
    ) -> bool:
        """Pretend Liquidsoap is ready for startup tests."""
        return True

    async def queue_track(
        self, filepath: str, *, title: str | None = None, artist: str | None = None
    ) -> bool:
        """Record a queued track path and its annotated metadata."""
        self.queued_tracks.append(filepath)
        if title is not None or artist is not None:
            self.metadata_updates.append((title or "", artist or "AI Radio"))
        return True

    async def queue_break(self, filepath: str, *, title: str | None = None) -> bool:
        """Record a queued DJ break path."""
        self.queued_breaks.append(filepath)
        return True

    async def get_now_playing_file(self) -> str | None:
        """Return the file the test has marked as currently on air."""
        return self.now_playing_file


def make_scheduler(fake_playout: FakePlayout | None = None) -> MasterScheduler:
    """Create a scheduler with external playout replaced by a fake."""
    scheduler = MasterScheduler()
    scheduler._playout = fake_playout or FakePlayout()
    return scheduler


async def air(scheduler: MasterScheduler, session, filepath) -> None:
    """Simulate Liquidsoap starting ``filepath`` on air and reconcile once.

    Mirrors the production flow where now-playing/playlog transitions happen
    at air time (driven by ``nowplaying.file``), not at queue time.
    """
    scheduler._playout.now_playing_file = str(filepath) if filepath else None
    await scheduler._reconcile_now_playing(session)


def runtime_path(tmp_path: Path, filename: str) -> Path:
    """Return a writable path for tests."""
    return tmp_path / filename


def patch_scheduler_session_factory(monkeypatch, engine: AsyncEngine) -> None:
    """Point scheduler-owned sessions at the current test database."""
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    monkeypatch.setattr(
        "server.engine.scheduler.get_session_factory",
        lambda: factory,
    )


@pytest.mark.asyncio
async def test_queue_next_track_marks_previous_playing_as_played_and_logs(
    db_session, monkeypatch, tmp_path
):
    """Queueing a track should update state, metadata, playlog, and events."""
    events = []
    monkeypatch.setattr(
        "server.engine.scheduler.event_bus.emit",
        lambda event, data=None: events.append((event, data or {})),
    )

    prev_file = runtime_path(tmp_path, "prev.wav")
    prev_file.write_bytes(b"fake wav")
    previous = Track(
        filepath=str(prev_file),
        title="Old Song",
        status="playing",
        played_at=datetime.now(timezone.utc),
    )
    audio_file = runtime_path(tmp_path, "next.wav")
    audio_file.write_bytes(b"fake wav")
    next_track = Track(
        filepath=str(audio_file),
        title="Next Song",
        style_prompt="bright synth pop",
        duration=180.0,
        status="ready",
    )
    db_session.add_all(
        [
            previous,
            next_track,
            DJConfig(station_name="Test FM", is_default=True),
        ]
    )
    await db_session.commit()

    fake_playout = FakePlayout()
    scheduler = make_scheduler(fake_playout)
    # Simulate the previous track already being on air.
    scheduler._on_air_path = str(prev_file)

    # Queueing only marks the track "queued" — no premature air-time state.
    await scheduler._queue_next_track(db_session)
    await db_session.refresh(next_track)
    assert next_track.status == "queued"
    assert fake_playout.queued_tracks == [str(audio_file)]
    assert fake_playout.metadata_updates == [("Next Song", "Test FM")]
    assert scheduler._dj_brain._tracks_since_break == 1
    assert (await db_session.execute(select(PlayLog))).scalars().first() is None

    # Liquidsoap starts the new track — the reconciler applies air-time state.
    await air(scheduler, db_session, audio_file)

    await db_session.refresh(previous)
    await db_session.refresh(next_track)
    assert previous.status == "played"
    assert next_track.status == "playing"
    assert next_track.played_at is not None

    logs = (await db_session.execute(select(PlayLog))).scalars().all()
    assert len(logs) == 1
    assert logs[0].item_type == "track"
    assert logs[0].item_id == next_track.id

    emitted = [event for event, _ in events]
    assert "track.ended" in emitted
    assert "track.started" in emitted


@pytest.mark.asyncio
async def test_queue_next_track_updates_timeline_lifecycle(
    db_session, monkeypatch, tmp_path, engine
):
    """Queueing music should mirror legacy play state into ProgramItem rows."""
    patch_scheduler_session_factory(monkeypatch, engine)
    monkeypatch.setattr(
        "server.engine.scheduler.event_bus.emit",
        lambda event, data=None: None,
    )

    prev_file = runtime_path(tmp_path, "timeline-prev.wav")
    prev_file.write_bytes(b"fake wav")
    previous = Track(
        filepath=str(prev_file),
        title="Old Song",
        status="playing",
        played_at=datetime.now(timezone.utc),
    )
    audio_file = runtime_path(tmp_path, "timeline-next.wav")
    audio_file.write_bytes(b"fake wav")
    next_track = Track(
        filepath=str(audio_file),
        title="Next Timeline Song",
        duration=180.0,
        status="ready",
    )
    db_session.add_all(
        [
            previous,
            next_track,
            DJConfig(station_name="Test FM", is_default=True),
        ]
    )
    await db_session.flush()
    previous_item = ProgramItem(
        item_type="music_track",
        status="playing",
        source_table="tracks",
        source_id=previous.id,
    )
    next_item = ProgramItem(
        item_type="music_track",
        status="ready",
        source_table="tracks",
        source_id=next_track.id,
    )
    db_session.add_all([previous_item, next_item])
    await db_session.commit()

    scheduler = make_scheduler(FakePlayout())
    scheduler._on_air_path = str(prev_file)

    await scheduler._queue_next_track(db_session)
    await air(scheduler, db_session, audio_file)

    await db_session.refresh(previous_item)
    await db_session.refresh(next_item)
    assert previous_item.status == "played"
    assert previous_item.ended_at is not None
    assert next_item.status == "playing"
    assert next_item.queued_at is not None
    assert next_item.started_at is not None


@pytest.mark.asyncio
async def test_queue_next_track_continues_when_timeline_playing_update_fails(
    db_session, monkeypatch, tmp_path, engine
):
    """Timeline playing failures should not break legacy music queueing."""
    patch_scheduler_session_factory(monkeypatch, engine)
    events = []
    monkeypatch.setattr(
        "server.engine.scheduler.event_bus.emit",
        lambda event, data=None: events.append((event, data or {})),
    )

    async def fail_timeline_update(*args, **kwargs):
        raise RuntimeError("timeline write unavailable")

    monkeypatch.setattr(
        "server.engine.scheduler.mark_source_playing",
        fail_timeline_update,
    )
    active_rollback = AsyncMock(
        side_effect=AssertionError("active scheduler session rolled back")
    )
    monkeypatch.setattr(db_session, "rollback", active_rollback)

    audio_file = runtime_path(tmp_path, "timeline-playing-fails.wav")
    audio_file.write_bytes(b"fake wav")
    track = Track(
        filepath=str(audio_file),
        title="Resilient Song",
        style_prompt="steady house",
        duration=180.0,
        status="ready",
    )
    db_session.add_all(
        [
            track,
            DJConfig(station_name="Test FM", is_default=True),
        ]
    )
    await db_session.commit()

    fake_playout = FakePlayout()
    scheduler = make_scheduler(fake_playout)

    await scheduler._queue_next_track(db_session)
    await air(scheduler, db_session, audio_file)

    await db_session.refresh(track)
    assert track.status == "playing"
    assert fake_playout.queued_tracks == [str(audio_file)]
    assert fake_playout.metadata_updates == [("Resilient Song", "Test FM")]

    logs = (await db_session.execute(select(PlayLog))).scalars().all()
    assert len(logs) == 1
    assert logs[0].item_type == "track"
    assert logs[0].item_id == track.id

    assert "track.started" in [event for event, _ in events]
    active_rollback.assert_not_awaited()


@pytest.mark.asyncio
async def test_queue_next_track_marks_missing_audio_timeline_failed(
    db_session, monkeypatch, tmp_path, engine
):
    """Missing music audio should fail the matching timeline item."""
    patch_scheduler_session_factory(monkeypatch, engine)
    missing_file = runtime_path(tmp_path, "timeline-missing.wav")
    track = Track(
        filepath=str(missing_file),
        title="Missing Timeline Song",
        duration=180.0,
        status="ready",
    )
    db_session.add(track)
    await db_session.flush()
    item = ProgramItem(
        item_type="music_track",
        status="ready",
        source_table="tracks",
        source_id=track.id,
    )
    db_session.add(item)
    await db_session.commit()

    scheduler = make_scheduler(FakePlayout())

    await scheduler._queue_next_track(db_session)

    await db_session.refresh(track)
    await db_session.refresh(item)
    assert track.status == "failed"
    assert item.status == "failed"
    assert item.ended_at is not None


@pytest.mark.asyncio
async def test_queue_next_talk_segment_marks_missing_audio_timeline_failed(
    db_session, monkeypatch, tmp_path, engine
):
    """Missing talk audio should fail the matching timeline item."""
    patch_scheduler_session_factory(monkeypatch, engine)
    missing_file = runtime_path(tmp_path, "missing-talk.wav")
    show = Show(id=1, name="Talk", show_type="talk", talk_config_id=1)
    segment = TalkSegment(
        show_id=1,
        talk_config_id=1,
        segment_type="conversation",
        audio_filepath=str(missing_file),
        duration=60.0,
        status="ready",
    )
    db_session.add_all([show, segment])
    await db_session.flush()
    item = ProgramItem(
        item_type="talk_segment",
        status="ready",
        source_table="talk_segments",
        source_id=segment.id,
    )
    db_session.add(item)
    await db_session.commit()

    scheduler = make_scheduler(FakePlayout())

    queued = await scheduler._queue_next_talk_segment(db_session, show)

    await db_session.refresh(segment)
    await db_session.refresh(item)
    assert queued is False
    assert segment.status == "failed"
    assert item.status == "failed"
    assert item.ended_at is not None


@pytest.mark.asyncio
async def test_queue_next_track_continues_when_timeline_failed_update_fails(
    db_session, monkeypatch, tmp_path, engine
):
    """Timeline failed-state errors should not escape missing-audio handling."""
    patch_scheduler_session_factory(monkeypatch, engine)

    async def fail_timeline_update(*args, **kwargs):
        raise RuntimeError("timeline write unavailable")

    monkeypatch.setattr(
        "server.engine.scheduler.mark_source_failed",
        fail_timeline_update,
    )
    active_rollback = AsyncMock(
        side_effect=AssertionError("active scheduler session rolled back")
    )
    monkeypatch.setattr(db_session, "rollback", active_rollback)

    missing_file = runtime_path(tmp_path, "timeline-failed-fails.wav")
    track = Track(
        filepath=str(missing_file),
        title="Missing But Handled",
        duration=180.0,
        status="ready",
    )
    db_session.add(track)
    await db_session.commit()

    fake_playout = FakePlayout()
    scheduler = make_scheduler(fake_playout)

    await scheduler._queue_next_track(db_session)

    await db_session.refresh(track)
    assert track.status == "failed"
    assert fake_playout.queued_tracks == []
    active_rollback.assert_not_awaited()


@pytest.mark.asyncio
async def test_queue_next_track_marks_missing_audio_failed(db_session, tmp_path):
    """A missing ready-track file should fail that track instead of queueing it."""
    missing_file = runtime_path(tmp_path, "missing.wav")
    track = Track(
        filepath=str(missing_file),
        title="Missing Song",
        duration=180.0,
        status="ready",
    )
    db_session.add(track)
    await db_session.commit()

    fake_playout = FakePlayout()
    scheduler = make_scheduler(fake_playout)

    await scheduler._queue_next_track(db_session)

    await db_session.refresh(track)
    assert track.status == "failed"
    assert fake_playout.queued_tracks == []


@pytest.mark.asyncio
async def test_empty_buffer_queues_fallback_audio(db_session, monkeypatch, tmp_path):
    """An empty ready buffer should trigger dead-air fallback."""
    events = []
    monkeypatch.setattr(
        "server.engine.scheduler.event_bus.emit",
        lambda event, data=None: events.append((event, data or {})),
    )

    fallback_dir = runtime_path(tmp_path, "fallback")
    fallback_dir.mkdir()
    fallback_file = fallback_dir / "fallback.wav"
    fallback_file.write_bytes(b"fake wav")

    fake_playout = FakePlayout()
    scheduler = make_scheduler(fake_playout)
    scheduler._fallback_dir = fallback_dir

    await scheduler._queue_next_track(db_session)

    assert fake_playout.queued_tracks == [str(fallback_file)]
    assert ("buffer.critical", {"ready": 0, "target": 0}) in events


@pytest.mark.asyncio
async def test_manage_talk_playout_marks_previous_segment_played(db_session, tmp_path):
    """Air-time reconcile should close a stale playing talk segment."""
    prev_file = runtime_path(tmp_path, "talk-prev.wav")
    prev_file.write_bytes(b"fake wav")
    previous = TalkSegment(
        segment_type="conversation",
        audio_filepath=str(prev_file),
        status="playing",
    )
    audio_file = runtime_path(tmp_path, "talk.wav")
    audio_file.write_bytes(b"fake wav")
    next_segment = TalkSegment(
        show_id=1,
        talk_config_id=1,
        segment_type="conversation",
        audio_filepath=str(audio_file),
        duration=60.0,
        status="ready",
    )
    show = Show(
        id=1,
        name="Morning Talk",
        show_type="talk",
        talk_config_id=1,
    )
    db_session.add_all([previous, next_segment, show])
    await db_session.commit()

    fake_playout = FakePlayout()
    scheduler = make_scheduler(fake_playout)
    scheduler._on_air_path = str(prev_file)

    await scheduler._manage_talk_playout(db_session, show)
    await db_session.refresh(next_segment)
    assert next_segment.status == "queued"
    assert fake_playout.queued_tracks == [str(audio_file)]

    await air(scheduler, db_session, audio_file)
    await db_session.refresh(previous)
    await db_session.refresh(next_segment)
    assert previous.status == "played"
    assert next_segment.status == "playing"


@pytest.mark.asyncio
async def test_manage_talk_playout_updates_timeline_lifecycle(
    db_session, monkeypatch, tmp_path, engine
):
    """Air-time reconcile should mirror talk state into ProgramItem rows."""
    patch_scheduler_session_factory(monkeypatch, engine)
    prev_file = runtime_path(tmp_path, "timeline-talk-prev.wav")
    prev_file.write_bytes(b"fake wav")
    previous = TalkSegment(
        segment_type="conversation",
        audio_filepath=str(prev_file),
        status="playing",
    )
    audio_file = runtime_path(tmp_path, "timeline-talk.wav")
    audio_file.write_bytes(b"fake wav")
    next_segment = TalkSegment(
        show_id=1,
        talk_config_id=1,
        segment_type="conversation",
        audio_filepath=str(audio_file),
        duration=60.0,
        status="ready",
    )
    show = Show(
        id=1,
        name="Morning Talk",
        show_type="talk",
        talk_config_id=1,
    )
    db_session.add_all([previous, next_segment, show])
    await db_session.flush()
    previous_item = ProgramItem(
        item_type="talk_segment",
        status="playing",
        source_table="talk_segments",
        source_id=previous.id,
    )
    next_item = ProgramItem(
        item_type="talk_segment",
        status="ready",
        source_table="talk_segments",
        source_id=next_segment.id,
    )
    db_session.add_all([previous_item, next_item])
    await db_session.commit()

    scheduler = make_scheduler(FakePlayout())
    scheduler._on_air_path = str(prev_file)

    await scheduler._manage_talk_playout(db_session, show)
    await air(scheduler, db_session, audio_file)

    await db_session.refresh(previous_item)
    await db_session.refresh(next_item)
    assert previous_item.status == "played"
    assert previous_item.ended_at is not None
    assert next_item.status == "playing"
    assert next_item.queued_at is not None
    assert next_item.started_at is not None


@pytest.mark.asyncio
async def test_hybrid_playout_queues_talk_after_music(db_session, tmp_path):
    """Hybrid shows should alternate into ready talk segments after music."""
    talk_file = runtime_path(tmp_path, "hybrid_talk.wav")
    talk_file.write_bytes(b"fake wav")
    show = Show(
        id=1,
        name="Hybrid Hour",
        show_type="hybrid",
        talk_config_id=1,
    )
    segment = TalkSegment(
        show_id=1,
        talk_config_id=1,
        segment_type="conversation",
        audio_filepath=str(talk_file),
        duration=45.0,
        status="ready",
    )
    db_session.add_all(
        [
            show,
            segment,
            PlayLog(item_type="track", item_id=99, duration=180.0),
        ]
    )
    await db_session.commit()

    fake_playout = FakePlayout(queue_length=0)
    scheduler = make_scheduler(fake_playout)
    scheduler._streaming = True
    scheduler._get_active_show = AsyncMock(return_value=show)
    scheduler._manage_playout = AsyncMock()

    await scheduler._playout_step(db_session)

    await db_session.refresh(segment)
    assert segment.status == "queued"
    assert fake_playout.queued_tracks == [str(talk_file)]
    scheduler._manage_playout.assert_not_awaited()


@pytest.mark.asyncio
async def test_hybrid_playout_queues_music_after_talk(db_session):
    """Hybrid shows should return to music after a talk segment."""
    show = Show(
        id=1,
        name="Hybrid Hour",
        show_type="hybrid",
        talk_config_id=1,
    )
    db_session.add_all(
        [
            show,
            PlayLog(item_type="talk_segment", item_id=42, duration=45.0),
        ]
    )
    await db_session.commit()

    fake_playout = FakePlayout(queue_length=0)
    scheduler = make_scheduler(fake_playout)
    scheduler._streaming = True
    scheduler._get_active_show = AsyncMock(return_value=show)
    scheduler._manage_playout = AsyncMock()

    await scheduler._playout_step(db_session)

    scheduler._manage_playout.assert_awaited_once()
    assert fake_playout.queued_tracks == []


@pytest.mark.asyncio
async def test_manage_playout_still_queues_track_when_break_generation_fails(
    db_session, tmp_path
):
    """DJ break failure must not prevent the next music track from queueing."""
    audio_file = runtime_path(tmp_path, "song.wav")
    audio_file.write_bytes(b"fake wav")
    track = Track(
        filepath=str(audio_file),
        title="Keep Playing",
        duration=180.0,
        status="ready",
    )
    db_session.add_all(
        [
            track,
            DJConfig(
                station_name="Test FM",
                break_frequency=1,
                break_frequency_variance=0,
                is_default=True,
            ),
        ]
    )
    await db_session.commit()

    fake_playout = FakePlayout(queue_length=0)
    scheduler = make_scheduler(fake_playout)
    scheduler._dj_brain.track_played()
    scheduler._dj_brain.generate_break = AsyncMock(
        side_effect=RuntimeError("voice provider down")
    )

    await scheduler._manage_playout(db_session)

    await db_session.refresh(track)
    assert fake_playout.queued_breaks == []
    assert fake_playout.queued_tracks == [str(audio_file)]
    assert track.status == "queued"


@pytest.mark.asyncio
async def test_manage_playout_leaves_single_pending_queue_item_alone(
    db_session, tmp_path
):
    """A single queued item is enough headroom and should not trigger more queueing."""
    audio_file = runtime_path(tmp_path, "pending-song.wav")
    audio_file.write_bytes(b"fake wav")
    track = Track(
        filepath=str(audio_file),
        title="Pending Song",
        duration=180.0,
        status="ready",
    )
    db_session.add_all(
        [
            track,
            DJConfig(
                station_name="Test FM",
                break_frequency=1,
                break_frequency_variance=0,
                is_default=True,
            ),
        ]
    )
    await db_session.commit()

    fake_playout = FakePlayout(queue_length=1)
    scheduler = make_scheduler(fake_playout)
    scheduler._dj_brain.track_played()
    scheduler._use_or_generate_break = AsyncMock(return_value=None)

    await scheduler._manage_playout(db_session)

    scheduler._use_or_generate_break.assert_not_awaited()
    assert fake_playout.queued_breaks == []
    assert fake_playout.queued_tracks == []
    await db_session.refresh(track)
    assert track.status == "ready"


@pytest.mark.asyncio
async def test_manage_playout_does_not_queue_music_behind_new_break(
    db_session, tmp_path
):
    """After queueing a DJ break, wait for a later tick before queueing music."""
    track_file = runtime_path(tmp_path, "after-break-song.wav")
    track_file.write_bytes(b"fake wav")
    break_file = runtime_path(tmp_path, "break.wav")
    break_file.write_bytes(b"fake wav")
    track = Track(
        filepath=str(track_file),
        title="After Break",
        duration=180.0,
        status="ready",
    )
    dj_break = DJBreak(
        audio_filepath=str(break_file),
        script_text="A short break.",
        duration=12.0,
        status="ready",
    )
    db_session.add_all(
        [
            track,
            dj_break,
            DJConfig(
                station_name="Test FM",
                break_frequency=1,
                break_frequency_variance=0,
                is_default=True,
            ),
        ]
    )
    await db_session.commit()

    fake_playout = FakePlayout(queue_length=0)
    scheduler = make_scheduler(fake_playout)
    scheduler._dj_brain.track_played()
    scheduler._use_or_generate_break = AsyncMock(return_value=dj_break)

    await scheduler._manage_playout(db_session)

    assert fake_playout.queued_breaks == [str(break_file)]
    assert fake_playout.queued_tracks == []
    await db_session.refresh(track)
    assert track.status == "ready"


@pytest.mark.asyncio
async def test_manage_playout_marks_queued_dj_break_timeline_playing(
    db_session, monkeypatch, tmp_path, engine
):
    """Queueing a DJ break should mark its ProgramItem as playing."""
    patch_scheduler_session_factory(monkeypatch, engine)
    break_file = runtime_path(tmp_path, "timeline-break.wav")
    break_file.write_bytes(b"fake wav")
    dj_break = DJBreak(
        audio_filepath=str(break_file),
        script_text="Timeline break",
        duration=12.0,
        status="ready",
    )
    db_session.add_all(
        [
            dj_break,
            DJConfig(
                station_name="Test FM",
                break_frequency=1,
                break_frequency_variance=0,
                is_default=True,
            ),
        ]
    )
    await db_session.flush()
    item = ProgramItem(
        item_type="dj_break",
        status="ready",
        source_table="dj_breaks",
        source_id=dj_break.id,
    )
    db_session.add(item)
    await db_session.commit()

    scheduler = make_scheduler(FakePlayout(queue_length=0))
    scheduler._dj_brain.should_break = lambda break_freq, break_var: True
    scheduler._dj_brain.should_prepare_break = lambda break_freq, break_var: False
    scheduler._use_or_generate_break = AsyncMock(return_value=dj_break)
    scheduler._queue_next_track = AsyncMock()

    await scheduler._manage_playout(db_session)
    await db_session.refresh(dj_break)
    assert dj_break.status == "queued"

    # Air-time reconcile flips the break's ProgramItem to playing.
    await air(scheduler, db_session, break_file)

    await db_session.refresh(item)
    assert item.status == "playing"
    assert item.queued_at is not None
    assert item.started_at is not None


@pytest.mark.asyncio
async def test_start_streaming_marks_active_show_seen_to_avoid_duplicate_intro(
    db_session, monkeypatch, engine
):
    """Startup should not generate a second show intro on the next transition tick."""
    patch_scheduler_session_factory(monkeypatch, engine)
    show = Show(
        name="Evening Block",
        show_type="music",
        active=True,
    )
    db_session.add(show)
    await db_session.flush()
    db_session.add(
        Station(
            setup_complete=True,
            broadcast_mode="manual",
            current_show_id=show.id,
        )
    )
    await db_session.commit()

    scheduler = make_scheduler(FakePlayout())
    scheduler._queue_startup_intro = AsyncMock()
    scheduler._dj_brain.generate_show_intro = AsyncMock(return_value=None)

    await scheduler.start_streaming()
    await scheduler._show_transition_step(db_session)

    assert scheduler._current_show_id == show.id
    assert scheduler._current_show_type == "music"
    scheduler._dj_brain.generate_show_intro.assert_not_awaited()


@pytest.mark.asyncio
async def test_cleanup_archives_played_tracks_and_marks_stale_playing(
    db_session, monkeypatch, tmp_path
):
    """Cleanup should archive played files and clear stale playing state."""
    audio_root = runtime_path(tmp_path, "audio_root")
    monkeypatch.setattr("server.engine.scheduler.settings.AUDIO_DIR", str(audio_root))

    tracks_dir = audio_root / "tracks"
    tracks_dir.mkdir(parents=True)
    audio_file = tracks_dir / "played.wav"
    audio_file.write_bytes(b"fake wav")

    played = Track(filepath=str(audio_file), title="Played", status="played")
    stale = Track(
        title="Stale",
        status="playing",
        played_at=datetime.now(timezone.utc) - timedelta(minutes=16),
    )
    db_session.add_all([Station(disk_retention_days=30), played, stale])
    await db_session.commit()

    scheduler = make_scheduler()
    await scheduler._run_cleanup(db_session)

    await db_session.refresh(played)
    await db_session.refresh(stale)
    archived_path = Path(played.filepath)
    assert played.status == "archived"
    assert archived_path.parent == audio_root / "archive"
    assert archived_path.exists()
    assert not audio_file.exists()
    assert stale.status == "played"


@pytest.mark.asyncio
async def test_reap_stuck_generations_fails_old_rows(db_session, monkeypatch):
    """Rows stuck in a transient state past the max age are marked failed."""
    from datetime import timedelta
    from server.engine.scheduler import STUCK_GENERATION_MAX_AGE
    from server.models.generation_job import GenerationJob
    from server.utils.timeutils import utcnow_naive

    old = utcnow_naive() - STUCK_GENERATION_MAX_AGE - timedelta(minutes=5)
    recent = utcnow_naive()

    stuck_track = Track(status="generating", created_at=old)
    fresh_track = Track(status="generating", created_at=recent)
    stuck_break = DJBreak(status="generating", script_text="x", created_at=old)
    stuck_job = GenerationJob(job_type="music", status="running", created_at=old)
    fresh_job = GenerationJob(job_type="music", status="running", created_at=recent)
    db_session.add_all([stuck_track, fresh_track, stuck_break, stuck_job, fresh_job])
    await db_session.commit()

    scheduler = make_scheduler()
    await scheduler._reap_stuck_generations(db_session)

    for row in (stuck_track, fresh_track, stuck_break, stuck_job, fresh_job):
        await db_session.refresh(row)

    assert stuck_track.status == "failed"
    assert stuck_break.status == "failed"
    assert stuck_job.status == "failed"
    assert stuck_job.finished_at is not None
    # Recent rows are left alone to finish.
    assert fresh_track.status == "generating"
    assert fresh_job.status == "running"


@pytest.mark.asyncio
async def test_reconcile_logs_fallback_at_air_time(db_session, tmp_path):
    """A fallback file reaching air is logged for compliance by the reconciler."""
    fallback = tmp_path / "fallback" / "Emergency.wav"
    fallback.parent.mkdir(parents=True, exist_ok=True)
    fallback.write_bytes(b"fake wav")

    scheduler = make_scheduler()
    await air(scheduler, db_session, fallback)

    logs = (await db_session.execute(select(PlayLog))).scalars().all()
    assert len(logs) == 1
    assert logs[0].item_type == "fallback"
    assert logs[0].item_id == 0


@pytest.mark.asyncio
async def test_reconcile_stamps_ended_at_on_previous_playlog(db_session, tmp_path):
    """When the on-air item changes, the previous playlog gets an ended_at."""
    a = runtime_path(tmp_path, "a.wav"); a.write_bytes(b"x")
    b = runtime_path(tmp_path, "b.wav"); b.write_bytes(b"x")
    track_a = Track(filepath=str(a), title="A", duration=100.0, status="queued")
    track_b = Track(filepath=str(b), title="B", duration=100.0, status="queued")
    db_session.add_all([track_a, track_b])
    await db_session.commit()

    scheduler = make_scheduler()
    await air(scheduler, db_session, a)   # A goes on air
    await air(scheduler, db_session, b)   # B takes over -> A closed

    logs = (await db_session.execute(
        select(PlayLog).order_by(PlayLog.id))).scalars().all()
    assert [l.item_id for l in logs] == [track_a.id, track_b.id]
    assert logs[0].ended_at is not None    # A's play was closed
    assert logs[1].ended_at is None        # B is still on air
    await db_session.refresh(track_a)
    await db_session.refresh(track_b)
    assert track_a.status == "played"
    assert track_b.status == "playing"


@pytest.mark.asyncio
async def test_reconcile_is_idempotent_for_already_playing_item(db_session, tmp_path):
    """An already-playing item is not re-logged (survives an app restart)."""
    f = runtime_path(tmp_path, "resume.wav"); f.write_bytes(b"x")
    track = Track(filepath=str(f), title="Resume", duration=100.0, status="playing")
    db_session.add(track)
    await db_session.commit()

    # Fresh scheduler (as after a restart) sees the same file already on air.
    scheduler = make_scheduler()
    await air(scheduler, db_session, f)

    logs = (await db_session.execute(select(PlayLog))).scalars().all()
    assert logs == []   # no duplicate play logged
    await db_session.refresh(track)
    assert track.status == "playing"
