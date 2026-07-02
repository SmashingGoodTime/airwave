# Timeline Reconciliation Dashboard Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add read-only scheduler parity diagnostics that compare legacy ready queues against the mirrored program timeline, then show the result in the Dashboard Program Timeline panel.

**Architecture:** Create a focused reconciliation helper that reads legacy source tables and `ProgramItem` rows without mutating them. Extend the existing timeline health endpoint and dashboard panel so operators can see whether timeline ordering agrees with the legacy scheduler before the project moves toward timeline-authoritative playout.

**Tech Stack:** Python 3.11+, FastAPI, SQLAlchemy async ORM, pytest async tests, React 18, Vite.

---

## File Structure

- Create `server/engine/timeline_reconciliation.py`: read-only source/timeline parity diagnostics.
- Create `tests/test_timeline_reconciliation.py`: helper-level tests for candidate alignment, drift, duplicate mirrors, and source readiness drift.
- Modify `server/routers/dashboard.py`: include reconciliation data in `GET /api/dashboard/timeline/health`.
- Modify `tests/test_routers.py`: assert timeline health exposes reconciliation data and issue codes.
- Modify `frontend/src/pages/Dashboard.jsx`: show scheduler parity and compact comparison details in the existing Program Timeline card.
- Modify `docs/architecture.md`: add one note that the dashboard now reports timeline parity while legacy playout remains authoritative.

---

### Task 1: Add Reconciliation Helper Tests

**Files:**
- Create: `tests/test_timeline_reconciliation.py`

- [ ] **Step 1: Write failing helper tests**

Create `tests/test_timeline_reconciliation.py` with:

```python
"""Tests for read-only timeline reconciliation diagnostics."""

from datetime import datetime, timezone

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from server.engine.timeline_reconciliation import build_timeline_reconciliation
from server.models.program_item import ProgramItem
from server.models.show import Show
from server.models.talk_segment import TalkSegment
from server.models.track import Track


def _dt(hour: int) -> datetime:
    return datetime(2026, 1, 1, hour, tzinfo=timezone.utc)


@pytest.mark.asyncio
async def test_reconciliation_reports_aligned_music_candidate(
    db_session: AsyncSession,
):
    track = Track(
        filepath="audio/tracks/one.wav",
        title="One",
        status="ready",
        created_at=_dt(1),
    )
    db_session.add(track)
    await db_session.flush()
    db_session.add(
        ProgramItem(
            item_type="music_track",
            status="ready",
            source_table="tracks",
            source_id=track.id,
            title=track.title,
            created_at=_dt(1),
        )
    )
    await db_session.commit()

    result = await build_timeline_reconciliation(db_session)

    assert result["parity_status"] == "aligned"
    assert result["summary"]["music_candidate_mismatch"] == 0
    assert result["comparisons"][0]["queue"] == "music"
    assert result["comparisons"][0]["aligned"] is True
    assert result["comparisons"][0]["legacy_source"]["source_id"] == track.id
    assert result["comparisons"][0]["timeline_source"]["source_id"] == track.id
    assert result["issues"] == []


@pytest.mark.asyncio
async def test_reconciliation_reports_music_candidate_mismatch(
    db_session: AsyncSession,
):
    first = Track(
        filepath="audio/tracks/first.wav",
        title="First",
        status="ready",
        created_at=_dt(1),
    )
    second = Track(
        filepath="audio/tracks/second.wav",
        title="Second",
        status="ready",
        created_at=_dt(2),
    )
    db_session.add_all([first, second])
    await db_session.flush()
    db_session.add_all(
        [
            ProgramItem(
                item_type="music_track",
                status="ready",
                source_table="tracks",
                source_id=second.id,
                title=second.title,
                created_at=_dt(1),
            ),
            ProgramItem(
                item_type="music_track",
                status="ready",
                source_table="tracks",
                source_id=first.id,
                title=first.title,
                created_at=_dt(3),
            ),
        ]
    )
    await db_session.commit()

    result = await build_timeline_reconciliation(db_session)

    assert result["parity_status"] == "drifting"
    assert result["summary"]["music_candidate_mismatch"] == 1
    comparison = next(c for c in result["comparisons"] if c["queue"] == "music")
    assert comparison["aligned"] is False
    assert comparison["legacy_source"]["source_id"] == first.id
    assert comparison["timeline_source"]["source_id"] == second.id
    assert {issue["code"] for issue in result["issues"]} == {
        "music_candidate_mismatch"
    }


@pytest.mark.asyncio
async def test_reconciliation_reports_duplicate_source_mirrors(
    db_session: AsyncSession,
):
    track = Track(
        filepath="audio/tracks/dup.wav",
        title="Duplicate",
        status="ready",
        created_at=_dt(1),
    )
    db_session.add(track)
    await db_session.flush()
    db_session.add_all(
        [
            ProgramItem(
                item_type="music_track",
                status="ready",
                source_table="tracks",
                source_id=track.id,
            ),
            ProgramItem(
                item_type="music_track",
                status="ready",
                source_table="tracks",
                source_id=track.id,
            ),
        ]
    )
    await db_session.commit()

    result = await build_timeline_reconciliation(db_session)

    assert result["parity_status"] == "needs_attention"
    assert result["summary"]["duplicate_source_mirrors"] == 1
    assert "duplicate_source_mirrors" in {
        issue["code"] for issue in result["issues"]
    }


@pytest.mark.asyncio
async def test_reconciliation_reports_source_readiness_drift(
    db_session: AsyncSession,
):
    missing_timeline = Track(
        filepath="audio/tracks/missing-timeline.wav",
        title="Missing Timeline",
        status="ready",
        created_at=_dt(1),
    )
    not_ready_source = Track(
        filepath="audio/tracks/not-ready.wav",
        title="Not Ready",
        status="played",
        created_at=_dt(2),
    )
    db_session.add_all([missing_timeline, not_ready_source])
    await db_session.flush()
    db_session.add(
        ProgramItem(
            item_type="music_track",
            status="ready",
            source_table="tracks",
            source_id=not_ready_source.id,
            title=not_ready_source.title,
        )
    )
    await db_session.commit()

    result = await build_timeline_reconciliation(db_session)

    assert result["parity_status"] == "needs_attention"
    assert result["summary"]["legacy_ready_missing_timeline"] == 1
    assert result["summary"]["timeline_ready_source_not_ready"] == 1
    assert {
        "legacy_ready_missing_timeline",
        "timeline_ready_source_not_ready",
    }.issubset({issue["code"] for issue in result["issues"]})


@pytest.mark.asyncio
async def test_reconciliation_reports_talk_candidate_mismatch_per_show(
    db_session: AsyncSession,
):
    show = Show(name="Morning Talk", show_type="talk")
    db_session.add(show)
    await db_session.flush()
    first = TalkSegment(
        show_id=show.id,
        segment_type="monologue",
        audio_filepath="audio/talks/first.wav",
        status="ready",
        created_at=_dt(1),
    )
    second = TalkSegment(
        show_id=show.id,
        segment_type="monologue",
        audio_filepath="audio/talks/second.wav",
        status="ready",
        created_at=_dt(2),
    )
    db_session.add_all([first, second])
    await db_session.flush()
    db_session.add_all(
        [
            ProgramItem(
                item_type="talk_segment",
                status="ready",
                source_table="talk_segments",
                source_id=second.id,
                title="monologue",
                created_at=_dt(1),
            ),
            ProgramItem(
                item_type="talk_segment",
                status="ready",
                source_table="talk_segments",
                source_id=first.id,
                title="monologue",
                created_at=_dt(3),
            ),
        ]
    )
    await db_session.commit()

    result = await build_timeline_reconciliation(db_session)

    assert result["summary"]["talk_candidate_mismatch"] == 1
    comparison = next(c for c in result["comparisons"] if c["queue"] == "talk")
    assert comparison["show_id"] == show.id
    assert comparison["aligned"] is False
    assert comparison["legacy_source"]["source_id"] == first.id
    assert comparison["timeline_source"]["source_id"] == second.id
```

- [ ] **Step 2: Run tests to verify they fail**

Run:

```powershell
powershell -ExecutionPolicy Bypass -File scripts\test.ps1 tests\test_timeline_reconciliation.py
```

Expected: FAIL with `ModuleNotFoundError` or import error for `server.engine.timeline_reconciliation`.

---

### Task 2: Implement Reconciliation Helper

**Files:**
- Create: `server/engine/timeline_reconciliation.py`

- [ ] **Step 1: Add the read-only helper module**

Create `server/engine/timeline_reconciliation.py` with:

```python
"""Read-only diagnostics comparing legacy queues with program timeline rows."""

from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from server.models.dj_break import DJBreak
from server.models.program_item import ProgramItem
from server.models.talk_segment import TalkSegment
from server.models.track import Track


SOURCE_MODELS = (
    ("tracks", Track, Track.id),
    ("dj_breaks", DJBreak, DJBreak.id),
    ("talk_segments", TalkSegment, TalkSegment.id),
)


async def build_timeline_reconciliation(session: AsyncSession) -> dict[str, Any]:
    """Build read-only diagnostics comparing legacy ready queues to timeline rows."""
    duplicate_source_mirrors = await _count_duplicate_source_mirrors(session)
    legacy_ready_missing_timeline = await _count_legacy_ready_missing_timeline(session)
    timeline_ready_source_not_ready = await _count_timeline_ready_source_not_ready(
        session
    )

    comparisons = []
    music_comparison = await _compare_music_candidate(session)
    if music_comparison is not None:
        comparisons.append(music_comparison)
    comparisons.extend(await _compare_talk_candidates(session))

    music_candidate_mismatch = sum(
        1
        for comparison in comparisons
        if comparison["queue"] == "music" and not comparison["aligned"]
    )
    talk_candidate_mismatch = sum(
        1
        for comparison in comparisons
        if comparison["queue"] == "talk" and not comparison["aligned"]
    )

    summary = {
        "duplicate_source_mirrors": duplicate_source_mirrors,
        "music_candidate_mismatch": music_candidate_mismatch,
        "talk_candidate_mismatch": talk_candidate_mismatch,
        "legacy_ready_missing_timeline": legacy_ready_missing_timeline,
        "timeline_ready_source_not_ready": timeline_ready_source_not_ready,
    }
    issues = [
        _issue(
            "duplicate_source_mirrors",
            duplicate_source_mirrors,
            "timeline source mirrors are duplicated",
        ),
        _issue(
            "music_candidate_mismatch",
            music_candidate_mismatch,
            "music scheduler candidate differs from timeline candidate",
        ),
        _issue(
            "talk_candidate_mismatch",
            talk_candidate_mismatch,
            "talk scheduler candidate differs from timeline candidate",
        ),
        _issue(
            "legacy_ready_missing_timeline",
            legacy_ready_missing_timeline,
            "ready source rows have no timeline mirror",
        ),
        _issue(
            "timeline_ready_source_not_ready",
            timeline_ready_source_not_ready,
            "ready timeline rows point at missing or non-ready sources",
        ),
    ]
    issues = [issue for issue in issues if issue is not None]

    return {
        "parity_status": _parity_status(summary),
        "summary": summary,
        "comparisons": comparisons,
        "issues": issues,
    }


async def _compare_music_candidate(session: AsyncSession) -> dict[str, Any] | None:
    legacy = await _legacy_music_candidate(session)
    timeline = await _timeline_music_candidate(session)
    if legacy is None and timeline is None:
        return None
    return _comparison("music", None, legacy, timeline)


async def _compare_talk_candidates(session: AsyncSession) -> list[dict[str, Any]]:
    show_ids_result = await session.execute(
        select(TalkSegment.show_id)
        .where(TalkSegment.status == "ready", TalkSegment.show_id.is_not(None))
        .distinct()
    )
    comparisons = []
    for show_id in show_ids_result.scalars().all():
        legacy = await _legacy_talk_candidate(session, show_id)
        timeline = await _timeline_talk_candidate(session, show_id)
        if legacy is None and timeline is None:
            continue
        comparisons.append(_comparison("talk", show_id, legacy, timeline))
    return comparisons


async def _legacy_music_candidate(session: AsyncSession) -> dict[str, Any] | None:
    result = await session.execute(
        select(Track)
        .where(Track.status == "ready")
        .order_by(Track.created_at.asc(), Track.id.asc())
        .limit(1)
    )
    track = result.scalar_one_or_none()
    if track is None:
        return None
    return _source("tracks", track.id, track.title)


async def _timeline_music_candidate(session: AsyncSession) -> dict[str, Any] | None:
    result = await session.execute(
        select(ProgramItem)
        .join(Track, Track.id == ProgramItem.source_id)
        .where(
            ProgramItem.status == "ready",
            ProgramItem.item_type == "music_track",
            ProgramItem.source_table == "tracks",
            Track.status == "ready",
        )
        .order_by(
            ProgramItem.position.asc(),
            ProgramItem.planned_start_at.is_(None).asc(),
            ProgramItem.planned_start_at.asc(),
            ProgramItem.created_at.asc(),
            ProgramItem.id.asc(),
        )
        .limit(1)
    )
    item = result.scalar_one_or_none()
    if item is None:
        return None
    return _source("tracks", item.source_id, item.title)


async def _legacy_talk_candidate(
    session: AsyncSession, show_id: int
) -> dict[str, Any] | None:
    result = await session.execute(
        select(TalkSegment)
        .where(TalkSegment.status == "ready", TalkSegment.show_id == show_id)
        .order_by(TalkSegment.created_at.asc(), TalkSegment.id.asc())
        .limit(1)
    )
    segment = result.scalar_one_or_none()
    if segment is None:
        return None
    return _source("talk_segments", segment.id, segment.segment_type)


async def _timeline_talk_candidate(
    session: AsyncSession, show_id: int
) -> dict[str, Any] | None:
    result = await session.execute(
        select(ProgramItem)
        .join(TalkSegment, TalkSegment.id == ProgramItem.source_id)
        .where(
            ProgramItem.status == "ready",
            ProgramItem.item_type == "talk_segment",
            ProgramItem.source_table == "talk_segments",
            TalkSegment.status == "ready",
            TalkSegment.show_id == show_id,
        )
        .order_by(
            ProgramItem.position.asc(),
            ProgramItem.planned_start_at.is_(None).asc(),
            ProgramItem.planned_start_at.asc(),
            ProgramItem.created_at.asc(),
            ProgramItem.id.asc(),
        )
        .limit(1)
    )
    item = result.scalar_one_or_none()
    if item is None:
        return None
    return _source("talk_segments", item.source_id, item.title)


async def _count_duplicate_source_mirrors(session: AsyncSession) -> int:
    result = await session.execute(
        select(func.count())
        .select_from(
            select(
                ProgramItem.source_table,
                ProgramItem.source_id,
                func.count(ProgramItem.id).label("mirror_count"),
            )
            .where(
                ProgramItem.source_table.is_not(None),
                ProgramItem.source_id.is_not(None),
            )
            .group_by(ProgramItem.source_table, ProgramItem.source_id)
            .having(func.count(ProgramItem.id) > 1)
            .subquery()
        )
    )
    return result.scalar_one() or 0


async def _count_legacy_ready_missing_timeline(session: AsyncSession) -> int:
    total = 0
    for source_table, model, id_column in SOURCE_MODELS:
        total += await _count_unmirrored_ready_source(
            session, source_table, model, id_column
        )
    return total


async def _count_unmirrored_ready_source(
    session: AsyncSession,
    source_table: str,
    model: type,
    id_column: Any,
) -> int:
    result = await session.execute(
        select(func.count(id_column))
        .select_from(model)
        .outerjoin(
            ProgramItem,
            (ProgramItem.source_table == source_table)
            & (ProgramItem.source_id == id_column),
        )
        .where(model.status == "ready", ProgramItem.id.is_(None))
    )
    return result.scalar_one() or 0


async def _count_timeline_ready_source_not_ready(session: AsyncSession) -> int:
    total = 0
    total += await _count_ready_timeline_source_drift(session, "tracks", Track)
    total += await _count_ready_timeline_source_drift(session, "dj_breaks", DJBreak)
    total += await _count_ready_timeline_source_drift(
        session, "talk_segments", TalkSegment
    )
    return total


async def _count_ready_timeline_source_drift(
    session: AsyncSession,
    source_table: str,
    model: type,
) -> int:
    result = await session.execute(
        select(ProgramItem, model)
        .outerjoin(model, model.id == ProgramItem.source_id)
        .where(
            ProgramItem.status == "ready",
            ProgramItem.source_table == source_table,
        )
    )
    return sum(1 for _, source in result.all() if source is None or source.status != "ready")


def _comparison(
    queue: str,
    show_id: int | None,
    legacy: dict[str, Any] | None,
    timeline: dict[str, Any] | None,
) -> dict[str, Any]:
    return {
        "queue": queue,
        "show_id": show_id,
        "aligned": legacy == timeline,
        "legacy_source": legacy,
        "timeline_source": timeline,
    }


def _source(source_table: str, source_id: int | None, title: str | None) -> dict[str, Any] | None:
    if source_id is None:
        return None
    return {"source_table": source_table, "source_id": source_id, "title": title}


def _issue(code: str, count: int, message: str) -> dict[str, Any] | None:
    if count <= 0:
        return None
    return {"code": code, "count": count, "message": message}


def _parity_status(summary: dict[str, int]) -> str:
    if (
        summary["duplicate_source_mirrors"] > 0
        or summary["legacy_ready_missing_timeline"] > 0
        or summary["timeline_ready_source_not_ready"] > 0
    ):
        return "needs_attention"
    if (
        summary["music_candidate_mismatch"] > 0
        or summary["talk_candidate_mismatch"] > 0
    ):
        return "drifting"
    return "aligned"
```

- [ ] **Step 2: Run helper tests**

Run:

```powershell
powershell -ExecutionPolicy Bypass -File scripts\test.ps1 tests\test_timeline_reconciliation.py
```

Expected: all tests in `tests/test_timeline_reconciliation.py` pass.

---

### Task 3: Extend Timeline Health Endpoint

**Files:**
- Modify: `server/routers/dashboard.py`
- Modify: `tests/test_routers.py`

- [ ] **Step 1: Write failing router test**

In `tests/test_routers.py`, add this test inside `class TestDashboardRouter` after `test_timeline_health_reports_diagnostics`:

```python
    @pytest.mark.asyncio
    async def test_timeline_health_includes_reconciliation_diagnostics(
        self, client: AsyncClient, db_session: AsyncSession
    ):
        first = Track(
            filepath="audio/tracks/first.wav",
            title="First",
            status="ready",
            created_at=datetime(2026, 1, 1, 1, tzinfo=timezone.utc),
        )
        second = Track(
            filepath="audio/tracks/second.wav",
            title="Second",
            status="ready",
            created_at=datetime(2026, 1, 1, 2, tzinfo=timezone.utc),
        )
        db_session.add_all([first, second])
        await db_session.flush()
        db_session.add_all(
            [
                ProgramItem(
                    item_type="music_track",
                    status="ready",
                    source_table="tracks",
                    source_id=second.id,
                    title=second.title,
                    created_at=datetime(2026, 1, 1, 1, tzinfo=timezone.utc),
                ),
                ProgramItem(
                    item_type="music_track",
                    status="ready",
                    source_table="tracks",
                    source_id=first.id,
                    title=first.title,
                    created_at=datetime(2026, 1, 1, 3, tzinfo=timezone.utc),
                ),
            ]
        )
        await db_session.commit()

        resp = await client.get("/api/dashboard/timeline/health")

        assert resp.status_code == 200
        data = resp.json()
        assert data["healthy"] is False
        assert data["summary"]["music_candidate_mismatch"] == 1
        assert data["reconciliation"]["parity_status"] == "drifting"
        assert data["reconciliation"]["summary"]["music_candidate_mismatch"] == 1
        assert data["reconciliation"]["comparisons"][0]["aligned"] is False
        assert "music_candidate_mismatch" in {
            issue["code"] for issue in data["issues"]
        }
```

- [ ] **Step 2: Run router test to verify it fails**

Run:

```powershell
powershell -ExecutionPolicy Bypass -File scripts\test.ps1 tests\test_routers.py::TestDashboardRouter::test_timeline_health_includes_reconciliation_diagnostics
```

Expected: FAIL because the response has no `reconciliation` field or reconciliation summary keys yet.

- [ ] **Step 3: Import the helper**

In `server/routers/dashboard.py`, add this import with the other engine/model imports:

```python
from server.engine.timeline_reconciliation import build_timeline_reconciliation
```

- [ ] **Step 4: Merge reconciliation into the health response**

Inside `get_timeline_health`, after `recent_failed_jobs` is computed and before `summary = { ... }`, add:

```python
    reconciliation = await build_timeline_reconciliation(session)
```

Replace the existing `summary = { ... }` block with:

```python
    summary = {
        "unmirrored_ready_tracks": unmirrored_tracks,
        "unmirrored_ready_breaks": unmirrored_breaks,
        "unmirrored_ready_talk_segments": unmirrored_talk,
        "program_items_without_assets": program_items_without_assets,
        "ready_assets_missing_files": ready_assets_missing_files,
        "recent_failed_jobs": recent_failed_jobs,
        **reconciliation["summary"],
    }
```

After the existing `issues = [issue for issue in issues if issue is not None]` line, add:

```python
    issues.extend(reconciliation["issues"])
```

Replace the return statement with:

```python
    return {
        "healthy": not issues,
        "summary": summary,
        "issues": issues,
        "reconciliation": reconciliation,
    }
```

- [ ] **Step 5: Run router tests**

Run:

```powershell
powershell -ExecutionPolicy Bypass -File scripts\test.ps1 tests\test_routers.py::TestDashboardRouter::test_timeline_health_includes_reconciliation_diagnostics tests\test_routers.py::TestDashboardRouter::test_timeline_health_reports_diagnostics tests\test_routers.py::TestDashboardRouter::test_timeline_health_empty_is_healthy
```

Expected: the three selected timeline health router tests pass.

---

### Task 4: Surface Scheduler Parity in Dashboard

**Files:**
- Modify: `frontend/src/pages/Dashboard.jsx`

- [ ] **Step 1: Add parity helper functions**

After `timelineStatusColor(status)`, add:

```jsx
  function parityLabel(status) {
    if (status === 'needs_attention') return 'Needs attention'
    if (status === 'drifting') return 'Drifting'
    return 'Aligned'
  }

  function parityBadgeClass(status) {
    if (status === 'aligned') return 'badge-active'
    return 'badge-inactive'
  }
```

- [ ] **Step 2: Add reconciliation derived values**

After the existing `const timelineIssueCount = ...` line, add:

```jsx
  const reconciliation = timelineHealth?.reconciliation || null
  const parityStatus = reconciliation?.parity_status || (timelineHealth?.healthy ? 'aligned' : 'needs_attention')
  const candidateComparisons = reconciliation?.comparisons || []
```

- [ ] **Step 3: Show the scheduler parity badge in the Program Timeline header**

Inside the Program Timeline card header, before the existing health badge, add:

```jsx
            <span className={`badge ${parityBadgeClass(parityStatus)}`}>
              Scheduler parity: {parityLabel(parityStatus)}
            </span>
```

- [ ] **Step 4: Show compact candidate comparison details**

After the existing timeline issue badge block and before the timeline filter buttons, add:

```jsx
        {candidateComparisons.length > 0 && (
          <div style={{ display: 'flex', flexDirection: 'column', gap: 6, marginBottom: 12 }}>
            {candidateComparisons.map((comparison, i) => {
              const legacy = comparison.legacy_source
              const timeline = comparison.timeline_source
              return (
                <div
                  key={`${comparison.queue}-${comparison.show_id || 'global'}-${i}`}
                  style={{ color: '#a0a0b8', fontSize: '0.78rem' }}
                >
                  <strong style={{ color: comparison.aligned ? '#66bb6a' : '#ff6b6b' }}>
                    {comparison.queue}{comparison.show_id ? ` #${comparison.show_id}` : ''}
                  </strong>
                  {' legacy '}
                  {legacy ? `${legacy.source_table}:${legacy.source_id} ${legacy.title || ''}` : 'none'}
                  {' / timeline '}
                  {timeline ? `${timeline.source_table}:${timeline.source_id} ${timeline.title || ''}` : 'none'}
                </div>
              )
            })}
          </div>
        )}
```

- [ ] **Step 5: Build the frontend**

Run:

```powershell
Set-Location frontend
npm run build
```

Expected: Vite build succeeds.

---

### Task 5: Architecture Note and Full Verification

**Files:**
- Modify: `docs/architecture.md`

- [ ] **Step 1: Add architecture note**

In `docs/architecture.md`, append this sentence to the timeline foundation or scheduler shadow lifecycle section:

```markdown
The dashboard timeline health endpoint now also reports read-only scheduler parity diagnostics, comparing legacy next-play candidates against timeline candidates without allowing the timeline to drive playout.
```

- [ ] **Step 2: Run focused backend verification**

Run:

```powershell
powershell -ExecutionPolicy Bypass -File scripts\test.ps1 tests\test_timeline_reconciliation.py tests\test_routers.py
```

Expected: selected backend tests pass.

- [ ] **Step 3: Run full backend verification**

Run:

```powershell
powershell -ExecutionPolicy Bypass -File scripts\test.ps1
```

Expected: full backend test suite passes.

- [ ] **Step 4: Run frontend verification**

Run:

```powershell
Set-Location frontend
npm run build
```

Expected: Vite build succeeds.

- [ ] **Step 5: Confirm no playout behavior changed**

Inspect the diff and confirm these files were not modified:

```text
server/engine/scheduler.py
server/engine/music_buffer.py
server/engine/dj_brain.py
server/engine/playout.py
```

If any of those files changed during implementation, revert only the unintended edits from this task and rerun the focused backend verification.
