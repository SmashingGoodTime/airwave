# Timeline Shadow Queue Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Record scheduler playout lifecycle changes into existing `ProgramItem` rows without making the timeline authoritative.

**Architecture:** Add a focused `server/engine/timeline_state.py` module that updates existing timeline mirror rows by `source_table` and `source_id`. The scheduler keeps all existing selection and Liquidsoap behavior, then records timeline state after legacy changes have already been committed so timeline failures cannot block broadcast playout.

**Tech Stack:** Python 3.11+, FastAPI project code, SQLAlchemy async ORM, pytest async tests.

---

## File Structure

- Create `server/engine/timeline_state.py`: source-oriented lifecycle helpers for existing `ProgramItem` rows.
- Create `tests/test_timeline_state.py`: unit tests for lifecycle helper behavior and idempotency.
- Modify `server/engine/scheduler.py`: call lifecycle helpers after successful legacy queue/commit paths and after legacy failure commits.
- Modify `tests/test_scheduler_reliability.py`: add scheduler-level tests for music, talk segment, and DJ break timeline lifecycle updates.
- Modify `docs/architecture.md`: document that timeline rows now shadow playout lifecycle, while legacy scheduler remains authoritative.

---

### Task 1: Timeline Lifecycle Helpers

**Files:**
- Create: `server/engine/timeline_state.py`
- Create: `tests/test_timeline_state.py`

- [ ] **Step 1: Write failing lifecycle helper tests**

Create `tests/test_timeline_state.py` with:

```python
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
    ended_at = datetime.now(timezone.utc)
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
```

- [ ] **Step 2: Run helper tests to verify RED**

Run:

```powershell
powershell -ExecutionPolicy Bypass -File scripts\test.ps1 tests\test_timeline_state.py
```

Expected: FAIL with `ModuleNotFoundError: No module named 'server.engine.timeline_state'`.

- [ ] **Step 3: Implement lifecycle helpers**

Create `server/engine/timeline_state.py` with:

```python
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
```

- [ ] **Step 4: Run helper tests to verify GREEN**

Run:

```powershell
powershell -ExecutionPolicy Bypass -File scripts\test.ps1 tests\test_timeline_state.py
```

Expected: PASS.

---

### Task 2: Music Track Timeline Recording

**Files:**
- Modify: `tests/test_scheduler_reliability.py`
- Modify: `server/engine/scheduler.py`

- [ ] **Step 1: Write failing scheduler tests for music timeline updates**

In `tests/test_scheduler_reliability.py`, add this import near the existing model imports:

```python
from server.models.program_item import ProgramItem
```

Append these tests after `test_queue_next_track_marks_previous_playing_as_played_and_logs`:

```python
@pytest.mark.asyncio
async def test_queue_next_track_updates_timeline_lifecycle(
    db_session, monkeypatch, tmp_path
):
    """Queueing music should mirror legacy play state into ProgramItem rows."""
    monkeypatch.setattr(
        "server.engine.scheduler.event_bus.emit",
        lambda event, data=None: None,
    )

    previous = Track(
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

    await scheduler._queue_next_track(db_session)

    await db_session.refresh(previous_item)
    await db_session.refresh(next_item)
    assert previous_item.status == "played"
    assert previous_item.ended_at is not None
    assert next_item.status == "playing"
    assert next_item.queued_at is not None
    assert next_item.started_at is not None


@pytest.mark.asyncio
async def test_queue_next_track_marks_missing_audio_timeline_failed(
    db_session, tmp_path
):
    """Missing music audio should fail the matching timeline item."""
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
```

- [ ] **Step 2: Run music scheduler tests to verify RED**

Run:

```powershell
powershell -ExecutionPolicy Bypass -File scripts\test.ps1 tests\test_scheduler_reliability.py::test_queue_next_track_updates_timeline_lifecycle tests\test_scheduler_reliability.py::test_queue_next_track_marks_missing_audio_timeline_failed
```

Expected: FAIL because the legacy scheduler updates `Track` rows but does not update `ProgramItem` rows.

- [ ] **Step 3: Add scheduler imports and safe timeline wrapper**

In `server/engine/scheduler.py`, add:

```python
from collections.abc import Awaitable
```

Add the timeline imports near other engine imports:

```python
from server.engine.timeline_state import (
    mark_source_failed,
    mark_source_played,
    mark_source_playing,
)
```

Add this method inside `MasterScheduler`, near the other private helper methods:

```python
    async def _record_timeline_update(
        self,
        session: AsyncSession,
        operation: Awaitable[object],
    ) -> None:
        """Record a non-critical timeline update without blocking playout."""
        try:
            await operation
            await session.commit()
        except Exception as exc:
            await session.rollback()
            logger.warning("Timeline state update failed: %s", exc)
```

- [ ] **Step 4: Record music missing-audio and playing lifecycle**

In `_queue_next_track`, after:

```python
            track.status = "failed"
            await session.commit()
```

add:

```python
            await self._record_timeline_update(
                session,
                mark_source_failed(session, "tracks", track.id),
            )
```

In the successful queue branch, replace:

```python
            for prev_track in prev_result.scalars().all():
                prev_track.status = "played"
                event_bus.emit(
                    "track.ended",
                    {"track_id": prev_track.id, "title": prev_track.title},
                )
```

with:

```python
            previous_tracks = list(prev_result.scalars().all())
            for prev_track in previous_tracks:
                prev_track.status = "played"
                event_bus.emit(
                    "track.ended",
                    {"track_id": prev_track.id, "title": prev_track.title},
                )
```

After the existing:

```python
            await session.commit()
```

that commits `track.status = "playing"`, add:

```python
            for prev_track in previous_tracks:
                await self._record_timeline_update(
                    session,
                    mark_source_played(session, "tracks", prev_track.id),
                )
            await self._record_timeline_update(
                session,
                mark_source_playing(session, "tracks", track.id),
            )
```

- [ ] **Step 5: Run music scheduler tests to verify GREEN**

Run:

```powershell
powershell -ExecutionPolicy Bypass -File scripts\test.ps1 tests\test_scheduler_reliability.py::test_queue_next_track_updates_timeline_lifecycle tests\test_scheduler_reliability.py::test_queue_next_track_marks_missing_audio_timeline_failed
```

Expected: PASS.

---

### Task 3: Talk Segment Timeline Recording

**Files:**
- Modify: `tests/test_scheduler_reliability.py`
- Modify: `server/engine/scheduler.py`

- [ ] **Step 1: Write failing scheduler test for talk timeline updates**

Append this test after `test_manage_talk_playout_marks_previous_segment_played`:

```python
@pytest.mark.asyncio
async def test_manage_talk_playout_updates_timeline_lifecycle(
    db_session, tmp_path
):
    """Queueing talk should mirror legacy segment state into ProgramItem rows."""
    previous = TalkSegment(segment_type="conversation", status="playing")
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

    await scheduler._manage_talk_playout(db_session, show)

    await db_session.refresh(previous_item)
    await db_session.refresh(next_item)
    assert previous_item.status == "played"
    assert previous_item.ended_at is not None
    assert next_item.status == "playing"
    assert next_item.queued_at is not None
    assert next_item.started_at is not None
```

Append this test after `test_queue_next_track_marks_missing_audio_timeline_failed`:

```python
@pytest.mark.asyncio
async def test_queue_next_talk_segment_marks_missing_audio_timeline_failed(
    db_session, tmp_path
):
    """Missing talk audio should fail the matching timeline item."""
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

    queued = await scheduler._queue_next_talk_segment(
        db_session,
        show,
        fallback_to_dead_air=False,
    )

    await db_session.refresh(segment)
    await db_session.refresh(item)
    assert queued is False
    assert segment.status == "failed"
    assert item.status == "failed"
    assert item.ended_at is not None
```

- [ ] **Step 2: Run talk scheduler tests to verify RED**

Run:

```powershell
powershell -ExecutionPolicy Bypass -File scripts\test.ps1 tests\test_scheduler_reliability.py::test_manage_talk_playout_updates_timeline_lifecycle tests\test_scheduler_reliability.py::test_queue_next_talk_segment_marks_missing_audio_timeline_failed
```

Expected: FAIL because `TalkSegment` rows are updated but matching `ProgramItem` rows are not.

- [ ] **Step 3: Record talk missing-audio and playing lifecycle**

In `_queue_next_talk_segment`, after:

```python
            segment.status = "failed"
            await session.commit()
```

add:

```python
            await self._record_timeline_update(
                session,
                mark_source_failed(session, "talk_segments", segment.id),
            )
```

In the successful queue branch, replace:

```python
            for prev_segment in prev_result.scalars().all():
                prev_segment.status = "played"
                event_bus.emit(
                    "talk_segment.ended",
                    {"segment_id": prev_segment.id},
                )
```

with:

```python
            previous_segments = list(prev_result.scalars().all())
            for prev_segment in previous_segments:
                prev_segment.status = "played"
                event_bus.emit(
                    "talk_segment.ended",
                    {"segment_id": prev_segment.id},
                )
```

After the existing:

```python
            await session.commit()
```

that commits `segment.status = "playing"`, add:

```python
            for prev_segment in previous_segments:
                await self._record_timeline_update(
                    session,
                    mark_source_played(
                        session,
                        "talk_segments",
                        prev_segment.id,
                    ),
                )
            await self._record_timeline_update(
                session,
                mark_source_playing(session, "talk_segments", segment.id),
            )
```

- [ ] **Step 4: Run talk scheduler tests to verify GREEN**

Run:

```powershell
powershell -ExecutionPolicy Bypass -File scripts\test.ps1 tests\test_scheduler_reliability.py::test_manage_talk_playout_updates_timeline_lifecycle tests\test_scheduler_reliability.py::test_queue_next_talk_segment_marks_missing_audio_timeline_failed
```

Expected: PASS.

---

### Task 4: DJ Break Timeline Recording

**Files:**
- Modify: `tests/test_scheduler_reliability.py`
- Modify: `server/engine/scheduler.py`

- [ ] **Step 1: Add DJ break imports for scheduler tests**

In `tests/test_scheduler_reliability.py`, add:

```python
from server.models.dj_break import DJBreak
```

- [ ] **Step 2: Write failing scheduler test for DJ break timeline updates**

Append this test after `test_manage_playout_still_queues_track_when_break_generation_fails`:

```python
@pytest.mark.asyncio
async def test_manage_playout_marks_queued_dj_break_timeline_playing(
    db_session, tmp_path
):
    """Queueing a DJ break should mark its ProgramItem as playing."""
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

    await db_session.refresh(item)
    assert item.status == "playing"
    assert item.queued_at is not None
    assert item.started_at is not None
```

- [ ] **Step 3: Run DJ break scheduler test to verify RED**

Run:

```powershell
powershell -ExecutionPolicy Bypass -File scripts\test.ps1 tests\test_scheduler_reliability.py::test_manage_playout_marks_queued_dj_break_timeline_playing
```

Expected: FAIL because queued DJ breaks are logged but their timeline row is not marked playing.

- [ ] **Step 4: Record DJ break playing lifecycle in all queue-break paths**

In `_manage_playout`, after the existing `_log_play` call inside the queued DJ break branch:

```python
                        await self._log_play(
                            session,
                            "dj_break",
                            dj_break.id,
                            dj_break.duration,
                        )
```

add:

```python
                        await self._record_timeline_update(
                            session,
                            mark_source_playing(
                                session,
                                "dj_breaks",
                                dj_break.id,
                            ),
                        )
```

In `_queue_startup_intro`, after the `_log_play` call for the queued intro, add:

```python
                        await self._record_timeline_update(
                            session,
                            mark_source_playing(
                                session,
                                "dj_breaks",
                                dj_break.id,
                            ),
                        )
```

In `_show_transition_step`, after the `_log_play` call for the queued intro, add:

```python
                            await self._record_timeline_update(
                                session,
                                mark_source_playing(
                                    session,
                                    "dj_breaks",
                                    intro.id,
                                ),
                            )
```

- [ ] **Step 5: Run DJ break scheduler test to verify GREEN**

Run:

```powershell
powershell -ExecutionPolicy Bypass -File scripts\test.ps1 tests\test_scheduler_reliability.py::test_manage_playout_marks_queued_dj_break_timeline_playing
```

Expected: PASS.

---

### Task 5: Documentation and Regression Verification

**Files:**
- Modify: `docs/architecture.md`

- [ ] **Step 1: Update architecture documentation**

In `docs/architecture.md`, after the paragraph ending with:

```markdown
The dashboard panels include status/type filters so operators can focus on
problems first and expand to the full history when needed.
```

add:

```markdown

The scheduler now also records playout lifecycle changes into the mirrored
timeline. When legacy tracks, DJ breaks, or talk segments are queued by the
existing scheduler, their matching `ProgramItem` rows move through `playing`,
`played`, or `failed` states. These lifecycle updates are still diagnostic:
legacy scheduler records remain authoritative, and timeline recording failures
are logged without stopping playout.
```

- [ ] **Step 2: Run focused test suite**

Run:

```powershell
powershell -ExecutionPolicy Bypass -File scripts\test.ps1 tests\test_timeline_state.py tests\test_scheduler_reliability.py tests\test_timeline_mirror.py
```

Expected: PASS.

- [ ] **Step 3: Run backend test suite**

Run:

```powershell
powershell -ExecutionPolicy Bypass -File scripts\test.ps1
```

Expected: PASS.

- [ ] **Step 4: Run frontend build**

Run:

```powershell
npm run build
```

from `D:\CLAUDE\Radio\frontend`.

Expected: Vite production build exits 0.

- [ ] **Step 5: Review changed files**

Run:

```powershell
git diff -- server\engine\timeline_state.py server\engine\scheduler.py tests\test_timeline_state.py tests\test_scheduler_reliability.py docs\architecture.md
```

Expected: Diff shows only timeline lifecycle helper code, scheduler recording calls, tests, and the architecture note.
