"""Streaming control endpoints for starting and stopping the broadcast."""

import logging
from typing import Optional
from fastapi import APIRouter, Request, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from server.database import get_session_factory
from server.models.station import Station, get_station
from server.models.show import Show
from server.utils.timeutils import to_utc_iso, utcnow_naive

router = APIRouter(prefix="/api/streaming", tags=["streaming"])
logger = logging.getLogger(__name__)


class StartStreamingRequest(BaseModel):
    """Request body for starting or switching a broadcast."""

    show_type: Optional[str] = None
    show_id: Optional[int] = None
    broadcast_mode: Optional[str] = None  # "manual" or "scheduled"


async def _apply_station_update(
    session: AsyncSession, body: StartStreamingRequest
) -> None:
    """Persist broadcast mode and current show from a start/switch request.

    Args:
        session: Async database session.
        body: The start/switch request body.

    Raises:
        HTTPException: 400 on an invalid broadcast_mode, 404 if the
            requested show does not exist.
    """
    station = await get_station(session)
    if not station:
        return
    if body.broadcast_mode:
        if body.broadcast_mode not in ("manual", "scheduled"):
            raise HTTPException(status_code=400, detail="Invalid broadcast_mode")
        station.broadcast_mode = body.broadcast_mode
    if body.show_id is not None:
        if body.show_id != 0:
            show_result = await session.execute(
                select(Show).where(Show.id == body.show_id)
            )
            if show_result.scalar_one_or_none() is None:
                raise HTTPException(status_code=404, detail="Show not found")
            station.current_show_id = body.show_id
        else:
            station.current_show_id = None
        station.current_show_started_at = utcnow_naive()
    await session.commit()


@router.get("/status")
async def get_streaming_status(request: Request) -> dict:
    """Get the current streaming state and station settings."""
    scheduler = request.app.state.scheduler

    factory = get_session_factory()
    async with factory() as session:
        station = await get_station(session)
        
        broadcast_mode = station.broadcast_mode if station else "manual"
        current_show_id = station.current_show_id if station else None
        current_show_started_at = (
            to_utc_iso(station.current_show_started_at) if station else None
        )
        
        active_show_name = None
        show_type = "music"
        duration_minutes = 30
        if current_show_id:
            show_result = await session.execute(select(Show).where(Show.id == current_show_id))
            show = show_result.scalar_one_or_none()
            if show:
                active_show_name = show.name
                show_type = show.show_type
                duration_minutes = show.duration_minutes

    return {
        "streaming": scheduler.is_streaming,
        "show_type": show_type,
        "broadcast_mode": broadcast_mode,
        "current_show_id": current_show_id,
        "active_show_name": active_show_name,
        "current_show_started_at": current_show_started_at,
        "duration_minutes": duration_minutes,
    }


@router.post("/start")
async def start_streaming(request: Request, body: StartStreamingRequest) -> dict:
    """Start the broadcast with the specified configuration."""
    scheduler = request.app.state.scheduler

    # Update Station settings in database
    factory = get_session_factory()
    async with factory() as session:
        await _apply_station_update(session, body)

    await scheduler.start_streaming()
    logger.info("Broadcast started via API")

    return {"status": "started"}


@router.post("/switch")
async def switch_streaming_mode(request: Request, body: StartStreamingRequest) -> dict:
    """Switch the broadcast mode or show configuration without stopping the stream."""
    scheduler = request.app.state.scheduler

    if not scheduler.is_streaming:
        raise HTTPException(status_code=400, detail="Not currently streaming.")

    # Update Station settings in database
    factory = get_session_factory()
    async with factory() as session:
        await _apply_station_update(session, body)

    # Tell scheduler to reload current show state immediately
    await scheduler.trigger_show_reload()
    logger.info("Broadcast settings updated via API")

    return {"status": "switched"}


@router.post("/stop")
async def stop_streaming(request: Request) -> dict:
    """Stop the broadcast."""
    scheduler = request.app.state.scheduler

    if not scheduler.is_streaming:
        return {"status": "not_streaming"}

    await scheduler.stop_streaming()
    logger.info("Broadcast stopped via API")

    return {"status": "stopped"}
