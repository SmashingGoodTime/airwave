"""Show schedule management API endpoints."""

from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field, field_serializer
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from server.database import get_session
from server.models.show import Show
from server.models.show_style import show_styles
from server.models.station import Station, get_station
from server.utils.timeutils import to_utc_iso

router = APIRouter(prefix="/api/shows", tags=["shows"])


class ShowCreate(BaseModel):
    """Schema for creating a new show block."""

    name: str = Field(min_length=1)
    active: bool = True
    duration_minutes: int = Field(default=30, ge=1, le=1440)
    queue_order: int = Field(default=0, ge=0)
    dj_config_id: Optional[int] = None
    style_ids: Optional[list[int]] = None


class ShowUpdate(BaseModel):
    """Schema for updating an existing show block."""

    name: Optional[str] = Field(default=None, min_length=1)
    active: Optional[bool] = None
    duration_minutes: Optional[int] = Field(default=None, ge=1, le=1440)
    queue_order: Optional[int] = Field(default=None, ge=0)
    dj_config_id: Optional[int] = None
    style_ids: Optional[list[int]] = None


class ShowResponse(BaseModel):
    """Schema for show block responses."""

    id: int
    name: str
    active: bool
    duration_minutes: int
    queue_order: int
    dj_config_id: Optional[int] = None
    style_ids: list[int] = []
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}

    @field_serializer("created_at", "updated_at")
    def _serialize_dt(self, value: Optional[datetime]) -> Optional[str]:
        return to_utc_iso(value)


async def _get_style_ids(session: AsyncSession, show_id: int) -> list[int]:
    """Load linked style IDs for a show from the junction table."""
    result = await session.execute(
        select(show_styles.c.style_id).where(show_styles.c.show_id == show_id)
    )
    return [row[0] for row in result.all()]


async def _sync_style_ids(
    session: AsyncSession, show_id: int, style_ids: list[int]
) -> None:
    """Replace the style associations for a show."""
    await session.execute(
        delete(show_styles).where(show_styles.c.show_id == show_id)
    )
    for sid in style_ids:
        await session.execute(
            show_styles.insert().values(show_id=show_id, style_id=sid)
        )


async def _show_to_response(session: AsyncSession, show: Show) -> ShowResponse:
    """Build a ShowResponse including style_ids from the junction table."""
    sids = await _get_style_ids(session, show.id)
    data = {c.key: getattr(show, c.key) for c in Show.__table__.columns}
    data["style_ids"] = sids
    return ShowResponse(**data)


@router.get("", response_model=list[ShowResponse])
async def list_shows(
    session: AsyncSession = Depends(get_session),
) -> list[ShowResponse]:
    """List all shows ordered by priority descending.

    Args:
        session: Async database session.

    Returns:
        List of all shows with style_ids.
    """
    result = await session.execute(select(Show).order_by(Show.queue_order.asc(), Show.id.asc()))
    shows = list(result.scalars().all())
    return [await _show_to_response(session, s) for s in shows]


@router.post("", response_model=ShowResponse, status_code=201)
async def create_show(
    body: ShowCreate,
    session: AsyncSession = Depends(get_session),
) -> ShowResponse:
    """Create a new show.

    Args:
        body: Show creation data.
        session: Async database session.

    Returns:
        The newly created show.
    """
    data = body.model_dump(exclude={"style_ids"})
    show = Show(**data)
    session.add(show)
    await session.flush()  # get show.id before inserting junction rows

    if body.style_ids:
        await _sync_style_ids(session, show.id, body.style_ids)

    await session.commit()
    await session.refresh(show)
    return await _show_to_response(session, show)


@router.put("/{show_id}", response_model=ShowResponse)
async def update_show(
    show_id: int,
    body: ShowUpdate,
    session: AsyncSession = Depends(get_session),
) -> ShowResponse:
    """Update an existing show.

    Args:
        show_id: ID of the show to update.
        body: Fields to update.
        session: Async database session.

    Returns:
        The updated show.
    """
    result = await session.execute(select(Show).where(Show.id == show_id))
    show = result.scalar_one_or_none()
    if show is None:
        raise HTTPException(status_code=404, detail="Show not found")

    update_data = body.model_dump(exclude_unset=True)
    style_ids = update_data.pop("style_ids", None)

    for key, value in update_data.items():
        setattr(show, key, value)

    if style_ids is not None:
        await _sync_style_ids(session, show.id, style_ids)

    await session.commit()
    await session.refresh(show)
    return await _show_to_response(session, show)


@router.delete("/{show_id}")
async def delete_show(
    show_id: int,
    session: AsyncSession = Depends(get_session),
) -> dict:
    """Delete a show.

    Args:
        show_id: ID of the show to delete.
        session: Async database session.

    Returns:
        Confirmation dict.
    """
    result = await session.execute(select(Show).where(Show.id == show_id))
    show = result.scalar_one_or_none()
    if show is None:
        raise HTTPException(status_code=404, detail="Show not found")

    # Clean up junction rows
    await session.execute(
        delete(show_styles).where(show_styles.c.show_id == show_id)
    )
    await session.delete(show)
    await session.commit()
    return {"success": True}


@router.get("/active", response_model=Optional[ShowResponse])
async def get_active_show(
    session: AsyncSession = Depends(get_session),
) -> ShowResponse | None:
    """Get the currently active show based on station broadcast state.

    Args:
        session: Async database session.

    Returns:
        The active show, or None.
    """
    station = await get_station(session)

    if station and station.current_show_id:
        result = await session.execute(
            select(Show).where(Show.id == station.current_show_id)
        )
        show = result.scalar_one_or_none()
        if show:
            return await _show_to_response(session, show)

    return None


@router.post("/{show_id}/toggle", response_model=ShowResponse)
async def toggle_show(
    show_id: int,
    session: AsyncSession = Depends(get_session),
) -> ShowResponse:
    """Toggle the active state of a show.

    Args:
        show_id: ID of the show to toggle.
        session: Async database session.

    Returns:
        The updated show.
    """
    result = await session.execute(select(Show).where(Show.id == show_id))
    show = result.scalar_one_or_none()
    if show is None:
        raise HTTPException(status_code=404, detail="Show not found")

    show.active = not show.active
    await session.commit()
    await session.refresh(show)
    return await _show_to_response(session, show)


class ReorderRequest(BaseModel):
    """Request body for reordering shows."""

    show_ids: list[int]


@router.post("/reorder")
async def reorder_shows(
    body: ReorderRequest,
    session: AsyncSession = Depends(get_session),
) -> dict:
    """Update the queue_order of shows based on the provided list of IDs."""
    for index, show_id in enumerate(body.show_ids):
        result = await session.execute(select(Show).where(Show.id == show_id))
        show = result.scalar_one_or_none()
        if show:
            show.queue_order = index
    await session.commit()
    return {"success": True}
