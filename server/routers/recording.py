"""Recording API endpoints for managing local stream recordings."""

import logging
from datetime import datetime, timezone
from pathlib import Path

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from fastapi import Depends

from server.config import settings
from server.database import get_session
from server.engine.playout import PlayoutInterface
from server.models.station import Station, get_station

router = APIRouter(prefix="/api/recording", tags=["recording"])
logger = logging.getLogger(__name__)

RECORDINGS_DIR = Path(settings.AUDIO_DIR) / "recordings"


def _get_playout() -> PlayoutInterface:
    """Get a playout interface instance."""
    return PlayoutInterface(
        host=settings.LIQUIDSOAP_HOST,
        port=settings.LIQUIDSOAP_PORT,
    )


class RecordingToggleRequest(BaseModel):
    """Request body for toggling recording."""
    enabled: bool


class RecordingSettingsRequest(BaseModel):
    """Request body for updating recording settings."""
    retention_days: int | None = None


@router.get("/status")
async def get_recording_status(
    session: AsyncSession = Depends(get_session),
) -> dict:
    """Get current recording status and settings.

    Args:
        session: Async database session.

    Returns:
        Recording enabled state, active status, and disk usage.
    """
    station = await get_station(session)

    enabled = station.recording_enabled if station else False
    retention_days = station.recording_retention_days if station else 7

    # Check if Liquidsoap recorder is actually running
    playout = _get_playout()
    is_active = await playout.is_recording()

    # Calculate disk usage of recordings
    disk_usage_mb = 0.0
    file_count = 0
    if RECORDINGS_DIR.exists():
        for f in RECORDINGS_DIR.iterdir():
            if f.is_file() and f.suffix in (".mp3", ".wav", ".ogg"):
                disk_usage_mb += f.stat().st_size / (1024 * 1024)
                file_count += 1

    return {
        "enabled": enabled,
        "active": is_active,
        "retention_days": retention_days,
        "disk_usage_mb": round(disk_usage_mb, 1),
        "file_count": file_count,
    }


@router.post("/toggle")
async def toggle_recording(
    body: RecordingToggleRequest,
    session: AsyncSession = Depends(get_session),
) -> dict:
    """Enable or disable stream recording.

    Args:
        body: Toggle request with enabled flag.
        session: Async database session.

    Returns:
        Updated recording status with the real recorder state.

    Raises:
        HTTPException: 404 if no station exists, 502 if Liquidsoap does not
            acknowledge the command (the DB state is left unchanged).
    """
    station = await get_station(session)
    if not station:
        raise HTTPException(status_code=404, detail="Station not configured")

    # Ensure recordings directory exists
    RECORDINGS_DIR.mkdir(parents=True, exist_ok=True)

    # Contact playout first; only persist the flag once Liquidsoap accepted
    # the command, so the DB never claims a recorder state playout rejected.
    playout = _get_playout()
    if body.enabled:
        acknowledged = await playout.start_recording()
    else:
        acknowledged = await playout.stop_recording()

    if not acknowledged:
        raise HTTPException(
            status_code=502,
            detail="Liquidsoap did not acknowledge the recording command",
        )

    station.recording_enabled = body.enabled
    await session.commit()
    logger.info(
        "Stream recording %s", "enabled" if body.enabled else "disabled"
    )

    is_active = await playout.is_recording()
    return {"enabled": body.enabled, "active": is_active}


@router.put("/settings")
async def update_recording_settings(
    body: RecordingSettingsRequest,
    session: AsyncSession = Depends(get_session),
) -> dict:
    """Update recording retention settings.

    Args:
        body: Settings to update.
        session: Async database session.

    Returns:
        Updated settings.
    """
    station = await get_station(session)
    if not station:
        raise HTTPException(status_code=404, detail="Station not configured")

    if body.retention_days is not None:
        station.recording_retention_days = max(1, body.retention_days)

    await session.commit()

    return {
        "retention_days": station.recording_retention_days,
    }


@router.get("/list")
async def list_recordings() -> list:
    """List all available recording files.

    Returns:
        A list of recording file info dicts sorted newest first.
    """
    if not RECORDINGS_DIR.exists():
        return []

    recordings = []
    for f in sorted(RECORDINGS_DIR.iterdir(), reverse=True):
        if f.is_file() and f.suffix in (".mp3", ".wav", ".ogg"):
            stat = f.stat()
            recordings.append({
                "filename": f.name,
                "size_mb": round(stat.st_size / (1024 * 1024), 1),
                "modified": datetime.fromtimestamp(
                    stat.st_mtime, tz=timezone.utc
                ).isoformat(),
                "duration_hint": _parse_duration_hint(f.name),
            })

    return recordings


@router.get("/download/{filename}")
async def download_recording(filename: str) -> FileResponse:
    """Download a recording file.

    Args:
        filename: Name of the recording file.

    Returns:
        The recording file as a download.
    """
    # Sanitize filename to prevent path traversal
    safe_name = Path(filename).name
    filepath = RECORDINGS_DIR / safe_name

    if not filepath.exists() or not filepath.is_file():
        raise HTTPException(status_code=404, detail="Recording not found")

    if not str(filepath.resolve()).startswith(str(RECORDINGS_DIR.resolve())):
        raise HTTPException(status_code=403, detail="Access denied")

    return FileResponse(
        path=str(filepath),
        filename=safe_name,
        media_type="audio/mpeg",
    )


@router.delete("/{filename}")
async def delete_recording(filename: str) -> dict:
    """Delete a recording file.

    Args:
        filename: Name of the recording file.

    Returns:
        Confirmation of deletion.
    """
    safe_name = Path(filename).name
    filepath = RECORDINGS_DIR / safe_name

    if not filepath.exists() or not filepath.is_file():
        raise HTTPException(status_code=404, detail="Recording not found")

    if not str(filepath.resolve()).startswith(str(RECORDINGS_DIR.resolve())):
        raise HTTPException(status_code=403, detail="Access denied")

    filepath.unlink()
    logger.info("Deleted recording: %s", safe_name)

    return {"deleted": safe_name}


def _parse_duration_hint(filename: str) -> str | None:
    """Extract a human-readable time hint from the filename pattern.

    The Liquidsoap recorder uses YYYY-MM-DD-HH.mp3 format.

    Args:
        filename: Recording filename.

    Returns:
        A human-readable date/hour string, or None.
    """
    stem = Path(filename).stem
    try:
        dt = datetime.strptime(stem, "%Y-%m-%d-%H")
        return dt.strftime("%B %d, %Y %I:00 %p")
    except ValueError:
        return None
