"""Stream URL API endpoint."""

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from server.config import settings
from server.database import get_session
from server.models.station import Station

router = APIRouter(prefix="/api/stream", tags=["stream"])


@router.get("/url")
async def get_stream_url(
    session: AsyncSession = Depends(get_session),
) -> dict:
    """Get the station stream URL.

    Args:
        session: Async database session.

    Returns:
        A dict with the stream URL.
    """
    result = await session.execute(
        select(Station).order_by(Station.id).limit(1)
    )
    station = result.scalar_one_or_none()
    url = station.stream_url if station and station.stream_url else settings.ICECAST_URL
    return {"url": url}
