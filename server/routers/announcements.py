"""Announcement management API endpoints."""

from datetime import datetime
from typing import Literal, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from server.database import get_session
from server.models.announcement import Announcement

router = APIRouter(prefix="/api/announcements", tags=["announcements"])


class AnnouncementCreate(BaseModel):
    """Schema for creating a new announcement."""

    text: str = Field(min_length=1)
    priority: Literal["low", "normal", "high", "urgent"] = "normal"
    active: bool = True
    expires_at: Optional[datetime] = None
    max_plays: Optional[int] = Field(default=None, ge=1)


class AnnouncementUpdate(BaseModel):
    """Schema for updating an existing announcement."""

    text: Optional[str] = Field(default=None, min_length=1)
    priority: Optional[Literal["low", "normal", "high", "urgent"]] = None
    active: Optional[bool] = None
    expires_at: Optional[datetime] = None
    max_plays: Optional[int] = Field(default=None, ge=1)


class AnnouncementResponse(BaseModel):
    """Schema for announcement responses."""

    id: int
    text: str
    priority: str
    active: bool
    expires_at: Optional[datetime] = None
    play_count: int
    max_plays: Optional[int] = None
    created_at: datetime

    model_config = {"from_attributes": True}


@router.get("", response_model=list[AnnouncementResponse])
async def list_announcements(
    active: Optional[bool] = Query(None),
    session: AsyncSession = Depends(get_session),
) -> list[Announcement]:
    """List all announcements with optional active filter.

    Args:
        active: If provided, filter by active status.
        session: Async database session.

    Returns:
        List of announcements.
    """
    stmt = select(Announcement)
    if active is not None:
        stmt = stmt.where(Announcement.active == active)
    result = await session.execute(stmt)
    return list(result.scalars().all())


@router.post("", response_model=AnnouncementResponse, status_code=201)
async def create_announcement(
    body: AnnouncementCreate,
    session: AsyncSession = Depends(get_session),
) -> Announcement:
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
    return announcement


@router.put("/{announcement_id}", response_model=AnnouncementResponse)
async def update_announcement(
    announcement_id: int,
    body: AnnouncementUpdate,
    session: AsyncSession = Depends(get_session),
) -> Announcement:
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
    return announcement


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
