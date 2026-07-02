"""Read-only diagnostics comparing legacy queues with program timeline rows."""

from typing import Any

from sqlalchemy import func, or_, select
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

    comparisons: list[dict[str, Any]] = []
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

    return {
        "parity_status": _parity_status(summary),
        "summary": summary,
        "comparisons": comparisons,
        "issues": [issue for issue in issues if issue is not None],
    }


async def _compare_music_candidate(session: AsyncSession) -> dict[str, Any] | None:
    legacy = await _legacy_music_candidate(session)
    timeline = await _timeline_music_candidate(session)
    if legacy is None and timeline is None:
        return None
    return _comparison("music", None, legacy, timeline)


async def _compare_talk_candidates(session: AsyncSession) -> list[dict[str, Any]]:
    legacy_by_show = await _legacy_talk_candidates_by_show(session)
    timeline_by_show = await _timeline_talk_candidates_by_show(session)

    comparisons = []
    for show_id, legacy in legacy_by_show.items():
        timeline = timeline_by_show.get(show_id)
        if legacy is None and timeline is None:
            continue
        comparisons.append(_comparison("talk", show_id, legacy, timeline))
    return comparisons


async def _legacy_talk_candidates_by_show(
    session: AsyncSession,
) -> dict[int, dict[str, Any]]:
    result = await session.execute(
        select(TalkSegment)
        .where(TalkSegment.status == "ready", TalkSegment.show_id.is_not(None))
        .order_by(
            TalkSegment.show_id.asc(),
            TalkSegment.created_at.asc(),
            TalkSegment.id.asc(),
        )
    )

    candidates: dict[int, dict[str, Any]] = {}
    for segment in result.scalars().all():
        if segment.show_id not in candidates:
            candidates[segment.show_id] = _source(
                "talk_segments", segment.id, segment.segment_type
            )
    return candidates


async def _timeline_talk_candidates_by_show(
    session: AsyncSession,
) -> dict[int, dict[str, Any]]:
    result = await session.execute(
        select(ProgramItem, TalkSegment.show_id)
        .join(TalkSegment, TalkSegment.id == ProgramItem.source_id)
        .where(
            ProgramItem.status == "ready",
            ProgramItem.item_type == "talk_segment",
            ProgramItem.source_table == "talk_segments",
            TalkSegment.status == "ready",
            TalkSegment.show_id.is_not(None),
        )
        .order_by(
            TalkSegment.show_id.asc(),
            ProgramItem.position.asc(),
            ProgramItem.planned_start_at.is_(None).asc(),
            ProgramItem.planned_start_at.asc(),
            ProgramItem.created_at.asc(),
            ProgramItem.id.asc(),
        )
    )

    candidates: dict[int, dict[str, Any]] = {}
    for item, show_id in result.all():
        if show_id not in candidates:
            candidates[show_id] = _source("talk_segments", item.source_id, item.title)
    return candidates


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


async def _count_duplicate_source_mirrors(session: AsyncSession) -> int:
    result = await session.execute(
        select(func.count()).select_from(
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
        select(func.count(ProgramItem.id))
        .outerjoin(model, model.id == ProgramItem.source_id)
        .where(
            ProgramItem.status == "ready",
            ProgramItem.source_table == source_table,
            or_(model.id.is_(None), model.status != "ready"),
        )
    )
    return result.scalar_one() or 0


def _comparison(
    queue: str,
    show_id: int | None,
    legacy: dict[str, Any] | None,
    timeline: dict[str, Any] | None,
) -> dict[str, Any]:
    return {
        "queue": queue,
        "show_id": show_id,
        "aligned": _same_source_identity(legacy, timeline),
        "legacy_source": legacy,
        "timeline_source": timeline,
    }


def _same_source_identity(
    legacy: dict[str, Any] | None, timeline: dict[str, Any] | None
) -> bool:
    if legacy is None or timeline is None:
        return legacy is None and timeline is None
    return (
        legacy["source_table"] == timeline["source_table"]
        and legacy["source_id"] == timeline["source_id"]
    )


def _source(
    source_table: str, source_id: int | None, title: str | None
) -> dict[str, Any] | None:
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
    if summary["music_candidate_mismatch"] > 0 or summary["talk_candidate_mismatch"] > 0:
        return "drifting"
    return "aligned"
