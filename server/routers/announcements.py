"""Announcement management API endpoints."""

from datetime import datetime, timezone
from typing import Literal, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field, field_serializer, field_validator
from sqlalchemy import case, select
from sqlalchemy.ext.asyncio import AsyncSession

from server.database import get_session
from server.models.announcement import Announcement
from server.utils.timeutils import parse_client_dt, to_utc_iso, utcnow_naive

router = APIRouter(prefix="/api/announcements", tags=["announcements"])

# SQL ordering for priorities: urgent > high > normal > low.
_PRIORITY_ORDER = case(
    (Announcement.priority == "urgent", 0),
    (Announcement.priority == "high", 1),
    (Announcement.priority == "normal", 2),
    else_=3,
)


def _normalize_expires_at(value: object) -> object:
    """Normalize a client-supplied expiry to naive UTC (storage convention).

    Args:
        value: The raw input (ISO string, datetime, or None).

    Returns:
        A naive UTC datetime, or the value unchanged if not parseable here
        (Pydantic performs its own type validation afterwards).

    Raises:
        ValueError: If a string value is not valid ISO 8601.
    """
    if isinstance(value, str):
        return parse_client_dt(value)
    if isinstance(value, datetime) and value.tzinfo is not None:
        return value.astimezone(timezone.utc).replace(tzinfo=None)
    return value


class AnnouncementCreate(BaseModel):
    """Schema for creating a new announcement."""

    text: str = Field(min_length=1)
    priority: Literal["low", "normal", "high", "urgent"] = "normal"
    active: bool = True
    expires_at: Optional[datetime] = None
    max_plays: Optional[int] = Field(default=None, ge=1)

    _parse_expires = field_validator("expires_at", mode="before")(
        _normalize_expires_at
    )


class AnnouncementUpdate(BaseModel):
    """Schema for updating an existing announcement."""

    text: Optional[str] = Field(default=None, min_length=1)
    priority: Optional[Literal["low", "normal", "high", "urgent"]] = None
    active: Optional[bool] = None
    expires_at: Optional[datetime] = None
    max_plays: Optional[int] = Field(default=None, ge=1)

    _parse_expires = field_validator("expires_at", mode="before")(
        _normalize_expires_at
    )


class AnnouncementResponse(BaseModel):
    """Schema for announcement responses.

    ``expired`` and ``plays_exhausted`` expose the auto-deactivation state
    so the UI can distinguish a manual toggle from an automatic one.
    """

    id: int
    text: str
    priority: str
    active: bool
    expires_at: Optional[datetime] = None
    play_count: int
    max_plays: Optional[int] = None
    created_at: datetime
    expired: bool = False
    plays_exhausted: bool = False

    model_config = {"from_attributes": True}

    @field_serializer("expires_at", "created_at")
    def _serialize_dt(self, value: Optional[datetime]) -> Optional[str]:
        return to_utc_iso(value)


def _to_response(announcement: Announcement) -> AnnouncementResponse:
    """Build a response with computed auto-deactivation flags.

    Args:
        announcement: The announcement ORM row.

    Returns:
        The response schema including ``expired`` and ``plays_exhausted``.
    """
    resp = AnnouncementResponse.model_validate(announcement)
    resp.expired = bool(
        announcement.expires_at and announcement.expires_at <= utcnow_naive()
    )
    resp.plays_exhausted = bool(
        announcement.max_plays is not None
        and announcement.play_count >= announcement.max_plays
    )
    return resp


@router.get("", response_model=list[AnnouncementResponse])
async def list_announcements(
    active: Optional[bool] = Query(None),
    session: AsyncSession = Depends(get_session),
) -> list[AnnouncementResponse]:
    """List all announcements with optional active filter.

    Ordered by active first, then priority (urgent to low), then newest.

    Args:
        active: If provided, filter by active status.
        session: Async database session.

    Returns:
        List of announcements.
    """
    stmt = select(Announcement)
    if active is not None:
        stmt = stmt.where(Announcement.active == active)
    stmt = stmt.order_by(
        Announcement.active.desc(),
        _PRIORITY_ORDER,
        Announcement.created_at.desc(),
    )
    result = await session.execute(stmt)
    return [_to_response(a) for a in result.scalars().all()]


@router.post("", response_model=AnnouncementResponse, status_code=201)
async def create_announcement(
    body: AnnouncementCreate,
    session: AsyncSession = Depends(get_session),
) -> AnnouncementResponse:
    """Create a new announcement.

    Args:
        body: Announcement creation data.
        session: Async database session.

    Returns:
        The newly created announcement.
    """
    announcement = Announcement(**body.model_dump())
    session.add(announcement)
    await session.commit()
    await session.refresh(announcement)
    return _to_response(announcement)


@router.put("/{announcement_id}", response_model=AnnouncementResponse)
async def update_announcement(
    announcement_id: int,
    body: AnnouncementUpdate,
    session: AsyncSession = Depends(get_session),
) -> AnnouncementResponse:
    """Update an existing announcement.

    Args:
        announcement_id: ID of the announcement to update.
        body: Fields to update.
        session: Async database session.

    Returns:
        The updated announcement.

    Raises:
        HTTPException: If the announcement is not found.
    """
    result = await session.execute(
        select(Announcement).where(Announcement.id == announcement_id)
    )
    announcement = result.scalar_one_or_none()
    if announcement is None:
        raise HTTPException(status_code=404, detail="Announcement not found")

    update_data = body.model_dump(exclude_unset=True)
    for key, value in update_data.items():
        setattr(announcement, key, value)

    await session.commit()
    await session.refresh(announcement)
    return _to_response(announcement)


@router.delete("/{announcement_id}")
async def delete_announcement(
    announcement_id: int,
    session: AsyncSession = Depends(get_session),
) -> dict:
    """Delete an announcement.

    Args:
        announcement_id: ID of the announcement to delete.
        session: Async database session.

    Returns:
        A dict confirming deletion.

    Raises:
        HTTPException: If the announcement is not found.
    """
    result = await session.execute(
        select(Announcement).where(Announcement.id == announcement_id)
    )
    announcement = result.scalar_one_or_none()
    if announcement is None:
        raise HTTPException(status_code=404, detail="Announcement not found")

    await session.delete(announcement)
    await session.commit()
    return {"success": True}
