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
async def test_reconciliation_ignores_stale_timeline_title_for_same_music_candidate(
    db_session: AsyncSession,
):
    track = Track(
        filepath="audio/tracks/renamed.wav",
        title="Fresh Source Title",
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
            title="Stale Timeline Title",
            created_at=_dt(1),
        )
    )
    await db_session.commit()

    result = await build_timeline_reconciliation(db_session)

    assert result["parity_status"] == "aligned"
    assert result["summary"]["music_candidate_mismatch"] == 0
    comparison = next(c for c in result["comparisons"] if c["queue"] == "music")
    assert comparison["aligned"] is True
    assert comparison["legacy_source"]["source_id"] == track.id
    assert comparison["timeline_source"]["source_id"] == track.id


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
