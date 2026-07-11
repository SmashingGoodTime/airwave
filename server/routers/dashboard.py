"""Dashboard API endpoints for real-time station monitoring."""

import asyncio
import json
import logging
from pathlib import Path

from fastapi import (
    APIRouter,
    Depends,
    HTTPException,
    Query,
    Request,
    WebSocket,
    WebSocketDisconnect,
)
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from server.database import get_session, get_session_factory
from server.engine.timeline_reconciliation import build_timeline_reconciliation
from server.events.emitter import event_bus
from server.models.audio_asset import AudioAsset
from server.models.dj_break import DJBreak
from server.models.generation_job import GenerationJob
from server.models.playlog import PlayLog
from server.models.program_item import ProgramItem
from server.models.show import Show
from server.models.station import Station, get_station
from server.models.talk_segment import TalkSegment
from server.models.track import Track
from server.providers.registry import ProviderRegistry
from server.utils.timeutils import to_utc_iso
from server.engine.timeline_reconciliation import count_unmirrored_ready_source

router = APIRouter(prefix="/api/dashboard", tags=["dashboard"])

# Cap on how many ready-asset files are checked per health request so the
# filesystem sweep stays bounded as the asset table grows.
ASSET_FILE_CHECK_LIMIT = 500

logger = logging.getLogger(__name__)


@router.get("/status")
async def get_dashboard_status(
    request: Request,
    session: AsyncSession = Depends(get_session),
) -> dict:
    """Get the current station dashboard status.

    Args:
        session: Async database session.

    Returns:
        A dict with now_playing, buffer_depth, provider_health,
        and stream_status fields.
    """
    # Now playing
    result = await session.execute(
        select(Track).where(Track.status == "playing").limit(1)
    )
    playing = result.scalar_one_or_none()
    now_playing = None
    if playing:
        now_playing = {
            "id": playing.id,
            "title": playing.title,
            "duration": playing.duration,
            "style": playing.style_prompt,
            "played_at": to_utc_iso(playing.played_at),
            "started_at": to_utc_iso(playing.played_at),
        }

    # Buffer depth
    result = await session.execute(
        select(func.count(Track.id)).where(Track.status == "ready")
    )
    buffer_depth = result.scalar() or 0

    # Provider health (lightweight — just check if configured)
    registry = ProviderRegistry.get_instance()
    provider_health = {
        "music": "configured" if registry.get_music_provider() else "unconfigured",
        "scriptwriter": (
            "configured"
            if registry.get_scriptwriter_provider()
            else "unconfigured"
        ),
        "voice": "configured" if registry.get_voice_provider() else "unconfigured",
    }

    # Active show
    station = await get_station(session)
    active_show = None
    active_show_info = None
    if station and station.current_show_id:
        show_result = await session.execute(
            select(Show).where(Show.id == station.current_show_id)
        )
        active_show = show_result.scalar_one_or_none()
        if active_show:
            active_show_info = {
                "id": active_show.id,
                "name": active_show.name,
                "show_type": active_show.show_type,
            }

    # Talk segment buffer (when in talk mode)
    talk_buffer_depth = 0
    if active_show and active_show.show_type in ("talk", "hybrid"):
        ts_result = await session.execute(
            select(func.count(TalkSegment.id)).where(
                TalkSegment.status == "ready",
                TalkSegment.show_id == active_show.id,
            )
        )
        talk_buffer_depth = ts_result.scalar() or 0

    # Active calls (removed CallSession)
    active_calls = 0

    # Streaming state
    scheduler = getattr(request.app.state, "scheduler", None)
    streaming = scheduler.is_streaming if scheduler else False
    streaming_show_type = scheduler.streaming_show_type if scheduler else None
    stream_status = "online" if streaming or now_playing else "idle"

    return {
        "now_playing": now_playing,
        "buffer_depth": buffer_depth,
        "buffer_target": station.buffer_target if station else 3,
        "buffer_warning": station.buffer_warning_threshold if station else 2,
        "provider_health": provider_health,
        "stream_status": stream_status,
        "active_show": active_show_info,
        "talk_buffer_depth": talk_buffer_depth,
        "active_calls": active_calls,
        "streaming": streaming,
        "streaming_show_type": streaming_show_type,
    }


@router.get("/recent")
async def get_recent_items(
    session: AsyncSession = Depends(get_session),
    limit: int = Query(20, ge=1, le=100),
) -> list:
    """Get recently played items.

    Args:
        session: Async database session.
        limit: Maximum number of items to return.

    Returns:
        A list of recent play log entries.
    """
    result = await session.execute(
        select(PlayLog).order_by(PlayLog.started_at.desc()).limit(limit)
    )
    items = []
    for log in result.scalars().all():
        metadata = {}
        if log.metadata_json:
            try:
                metadata = json.loads(log.metadata_json)
            except json.JSONDecodeError:
                pass
        items.append(
            {
                "id": log.id,
                "item_type": log.item_type,
                "type": log.item_type,
                "item_id": log.item_id,
                "started_at": to_utc_iso(log.started_at),
                "played_at": to_utc_iso(log.started_at),
                "timestamp": to_utc_iso(log.started_at),
                "duration": log.duration,
                "title": metadata.get("title", ""),
            }
        )
    return items


@router.get("/jobs")
async def get_generation_jobs(
    session: AsyncSession = Depends(get_session),
    limit: int = Query(20, ge=1, le=100),
) -> list:
    """Get recent generation jobs for operator diagnostics."""
    result = await session.execute(
        select(GenerationJob)
        .order_by(GenerationJob.created_at.desc())
        .limit(limit)
    )
    jobs = []
    for job in result.scalars().all():
        jobs.append(
            {
                "id": job.id,
                "uuid": job.uuid,
                "job_type": job.job_type,
                "capability": job.capability,
                "provider": job.provider,
                "status": job.status,
                "priority": job.priority,
                "attempts": job.attempts,
                "max_attempts": job.max_attempts,
                "input": _parse_json(job.input_json),
                "output": _parse_json(job.output_json),
                "output_asset_id": job.output_asset_id,
                "error_message": job.error_message,
                "scheduled_at": to_utc_iso(job.scheduled_at),
                "started_at": to_utc_iso(job.started_at),
                "finished_at": to_utc_iso(job.finished_at),
                "created_at": to_utc_iso(job.created_at),
            }
        )
    return jobs


@router.get("/timeline/health")
async def get_timeline_health(
    session: AsyncSession = Depends(get_session),
) -> dict:
    """Report consistency diagnostics for timeline mirror data."""
    unmirrored_tracks = await count_unmirrored_ready_source(
        session, "tracks", Track, Track.id
    )
    unmirrored_breaks = await count_unmirrored_ready_source(
        session, "dj_breaks", DJBreak, DJBreak.id
    )
    unmirrored_talk = await count_unmirrored_ready_source(
        session, "talk_segments", TalkSegment, TalkSegment.id
    )

    program_items_without_assets = await session.scalar(
        select(func.count(ProgramItem.id)).where(
            ProgramItem.status.in_(["ready", "queued", "playing", "played"]),
            ProgramItem.audio_asset_id.is_(None),
        )
    ) or 0

    # Bounded to the most recent assets so this endpoint stays fast as the
    # asset table grows; the blocking stat() sweep runs off the event loop.
    asset_result = await session.execute(
        select(AudioAsset.normalized_filepath)
        .where(
            AudioAsset.status == "ready",
            AudioAsset.normalized_filepath.is_not(None),
        )
        .order_by(AudioAsset.id.desc())
        .limit(ASSET_FILE_CHECK_LIMIT)
    )
    asset_paths = [row[0] for row in asset_result.all() if row[0]]
    ready_assets_missing_files = await asyncio.to_thread(
        _count_missing_files, asset_paths
    )

    recent_failed_jobs = await session.scalar(
        select(func.count(GenerationJob.id)).where(GenerationJob.status == "failed")
    ) or 0

    reconciliation = await build_timeline_reconciliation(session)

    summary = {
        "unmirrored_ready_tracks": unmirrored_tracks,
        "unmirrored_ready_breaks": unmirrored_breaks,
        "unmirrored_ready_talk_segments": unmirrored_talk,
        "program_items_without_assets": program_items_without_assets,
        "ready_assets_missing_files": ready_assets_missing_files,
        "recent_failed_jobs": recent_failed_jobs,
        **reconciliation["summary"],
    }
    issues = [
        _issue("unmirrored_ready_tracks", unmirrored_tracks, "ready tracks are not mirrored"),
        _issue("unmirrored_ready_breaks", unmirrored_breaks, "ready DJ breaks are not mirrored"),
        _issue(
            "unmirrored_ready_talk_segments",
            unmirrored_talk,
            "ready talk segments are not mirrored",
        ),
        _issue(
            "program_items_without_assets",
            program_items_without_assets,
            "timeline items have no audio asset",
        ),
        _issue(
            "ready_assets_missing_files",
            ready_assets_missing_files,
            "ready audio assets point at missing files",
        ),
        _issue(
            "recent_failed_jobs",
            recent_failed_jobs,
            "generation jobs are failed",
        ),
    ]
    issues = [issue for issue in issues if issue is not None]
    issues.extend(
        issue
        for issue in reconciliation["issues"]
        if issue["code"] != "legacy_ready_missing_timeline"
    )

    return {
        "healthy": not issues,
        "summary": summary,
        "issues": issues,
        "reconciliation": reconciliation,
    }


@router.get("/timeline")
async def get_timeline_items(
    session: AsyncSession = Depends(get_session),
    limit: int = Query(20, ge=1, le=100),
) -> list:
    """Get recent items from the new program timeline mirror.

    Args:
        session: Async database session.
        limit: Maximum number of items to return.

    Returns:
        A list of program timeline items with optional audio asset metadata.
    """
    result = await session.execute(
        select(ProgramItem, AudioAsset)
        .outerjoin(AudioAsset, ProgramItem.audio_asset_id == AudioAsset.id)
        .order_by(ProgramItem.created_at.desc())
        .limit(limit)
    )

    items = []
    for item, asset in result.all():
        items.append(
            {
                "id": item.id,
                "uuid": item.uuid,
                "item_type": item.item_type,
                "status": item.status,
                "title": item.title or "",
                "duration": item.duration,
                "source_table": item.source_table,
                "source_id": item.source_id,
                "audio_asset_id": item.audio_asset_id,
                "planned_start_at": to_utc_iso(item.planned_start_at),
                "queued_at": to_utc_iso(item.queued_at),
                "started_at": to_utc_iso(item.started_at),
                "ended_at": to_utc_iso(item.ended_at),
                "created_at": to_utc_iso(item.created_at),
                "asset": (
                    {
                        "id": asset.id,
                        "asset_type": asset.asset_type,
                        "normalized_filepath": asset.normalized_filepath,
                        "duration": asset.duration,
                        "loudness_lufs": asset.loudness_lufs,
                        "status": asset.status,
                    }
                    if asset
                    else None
                ),
            }
        )
    return items


def _parse_json(value: str | None) -> dict:
    """Parse a JSON object string, returning an empty dict on bad input."""
    if not value:
        return {}
    try:
        parsed = json.loads(value)
    except json.JSONDecodeError:
        return {}
    return parsed if isinstance(parsed, dict) else {}


def _count_missing_files(paths: list[str]) -> int:
    """Count paths that do not exist on disk (blocking; run in a thread)."""
    return sum(1 for path in paths if not Path(path).exists())


def _issue(code: str, count: int, message: str) -> dict | None:
    """Build an issue summary when a diagnostic count is non-zero."""
    if count <= 0:
        return None
    return {"code": code, "count": count, "message": message}


@router.get("/health")
async def get_health() -> dict:
    """Get provider health status.

    Returns:
        A dict with health status for each provider type.
    """
    registry = ProviderRegistry.get_instance()
    return await registry.check_all_health()


@router.websocket("/ws")
async def dashboard_websocket(websocket: WebSocket) -> None:
    """WebSocket endpoint for real-time dashboard updates.

    Connects the client to the event bus for live updates. Also sends
    periodic status snapshots so the dashboard stays fresh.

    Args:
        websocket: The WebSocket connection.
    """
    await websocket.accept()
    event_bus.connect_ws(websocket)

    scheduler = getattr(websocket.app.state, "scheduler", None)

    try:
        # Send initial status snapshot via the per-client queue so it never
        # interleaves with event-bus broadcast writes on the same socket.
        session_factory = get_session_factory()
        async with session_factory() as session:
            status = await _build_status_snapshot(session, scheduler)
            event_bus.send_ws(
                websocket,
                json.dumps(
                    {"type": "status.snapshot", "data": status}, default=str
                ),
            )

        # Keep alive with periodic status updates
        while True:
            try:
                # Wait for client messages (ping/pong) or timeout
                await asyncio.wait_for(websocket.receive_text(), timeout=10.0)
            except asyncio.TimeoutError:
                # Send periodic status update
                try:
                    async with session_factory() as session:
                        status = await _build_status_snapshot(session, scheduler)
                        event_bus.send_ws(
                            websocket,
                            json.dumps(
                                {"type": "status.snapshot", "data": status},
                                default=str,
                            ),
                        )
                except Exception:
                    logger.debug("Error building status snapshot for WS")

    except WebSocketDisconnect:
        logger.info("Dashboard WebSocket client disconnected")
    except Exception:
        logger.debug("WebSocket error, client disconnecting")
    finally:
        event_bus.disconnect_ws(websocket)


async def _build_status_snapshot(session: AsyncSession, scheduler=None) -> dict:
    """Build a status snapshot for WebSocket broadcast.

    Args:
        session: Async database session.
        scheduler: Optional MasterScheduler instance for streaming state.

    Returns:
        A dict with now_playing, buffer_depth, stream_status, and streaming state.
    """
    result = await session.execute(
        select(Track).where(Track.status == "playing").limit(1)
    )
    playing = result.scalar_one_or_none()
    now_playing = None
    if playing:
        now_playing = {
            "id": playing.id,
            "title": playing.title,
            "duration": playing.duration,
            "style": playing.style_prompt,
            "played_at": to_utc_iso(playing.played_at),
            "started_at": to_utc_iso(playing.played_at),
        }

    result = await session.execute(
        select(func.count(Track.id)).where(Track.status == "ready")
    )
    buffer_depth = result.scalar() or 0

    station = await get_station(session)

    streaming = scheduler.is_streaming if scheduler else False
    streaming_show_type = scheduler.streaming_show_type if scheduler else None
    stream_status = "online" if streaming or now_playing else "idle"

    return {
        "now_playing": now_playing,
        "buffer_depth": buffer_depth,
        "buffer_target": station.buffer_target if station else 3,
        "buffer_warning": station.buffer_warning_threshold if station else 2,
        "stream_status": stream_status,
        "streaming": streaming,
        "streaming_show_type": streaming_show_type,
    }


@router.get("/track/{track_id}/lyrics")
async def get_track_lyrics(
    track_id: int,
    session: AsyncSession = Depends(get_session),
) -> dict:
    """Get lyrics for a specific track.

    Args:
        track_id: The track ID.
        session: Async database session.

    Returns:
        A dict with track_id, title, and lyrics fields.
    """
    result = await session.execute(
        select(Track).where(Track.id == track_id)
    )
    track = result.scalar_one_or_none()
    if not track:
        raise HTTPException(status_code=404, detail="Track not found")
    return {
        "track_id": track.id,
        "title": track.title or "",
        "lyrics": track.lyrics or "",
    }


@router.get("/break/{break_id}/script")
async def get_break_script(
    break_id: int,
    session: AsyncSession = Depends(get_session),
) -> dict:
    """Get the script text for a specific DJ break.

    Args:
        break_id: The DJ break ID.
        session: Async database session.

    Returns:
        A dict with break_id, script_text, and duration fields.
    """
    result = await session.execute(
        select(DJBreak).where(DJBreak.id == break_id)
    )
    dj_break = result.scalar_one_or_none()
    if not dj_break:
        raise HTTPException(status_code=404, detail="DJ break not found")
    return {
        "break_id": dj_break.id,
        "script_text": dj_break.script_text or "",
        "duration": dj_break.duration or 0,
    }
