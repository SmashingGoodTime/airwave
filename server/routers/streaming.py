"""Streaming control endpoints for starting and stopping the broadcast."""

import logging
from typing import Optional
from datetime import datetime, timezone
from fastapi import APIRouter, Request, HTTPException
from pydantic import BaseModel
from sqlalchemy import select

from server.database import get_session_factory
from server.models.station import Station
from server.models.show import Show

router = APIRouter(prefix="/api/streaming", tags=["streaming"])
logger = logging.getLogger(__name__)


class StartStreamingRequest(BaseModel):
    """Request body for starting or switching a broadcast."""

    show_type: Optional[str] = None
    show_id: Optional[int] = None
    broadcast_mode: Optional[str] = None  # "manual" or "scheduled"


@router.get("/status")
async def get_streaming_status(request: Request) -> dict:
    """Get the current streaming state and station settings."""
    scheduler = request.app.state.scheduler
    
    factory = get_session_factory()
    async with factory() as session:
        result = await session.execute(select(Station).limit(1))
        station = result.scalar_one_or_none()
        
        broadcast_mode = station.broadcast_mode if station else "manual"
        current_show_id = station.current_show_id if station else None
        current_show_started_at = station.current_show_started_at.isoformat() if station and station.current_show_started_at else None
        
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
        result = await session.execute(select(Station).limit(1))
        station = result.scalar_one_or_none()
        if station:
            if body.broadcast_mode:
                if body.broadcast_mode not in ("manual", "scheduled"):
                    raise HTTPException(status_code=400, detail="Invalid broadcast_mode")
                station.broadcast_mode = body.broadcast_mode
            if body.show_id is not None:
                station.current_show_id = body.show_id if body.show_id != 0 else None
                station.current_show_started_at = datetime.now(timezone.utc)
            await session.commit()

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
        result = await session.execute(select(Station).limit(1))
        station = result.scalar_one_or_none()
        if station:
            if body.broadcast_mode:
                if body.broadcast_mode not in ("manual", "scheduled"):
                    raise HTTPException(status_code=400, detail="Invalid broadcast_mode")
                station.broadcast_mode = body.broadcast_mode
            if body.show_id is not None:
                station.current_show_id = body.show_id if body.show_id != 0 else None
                station.current_show_started_at = datetime.now(timezone.utc)
            await session.commit()

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
