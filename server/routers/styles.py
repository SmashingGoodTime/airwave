"""Style management API endpoints."""

import json
import re
from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field, field_serializer, field_validator
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from server.database import get_session
from server.models.show_style import show_styles
from server.models.style import Style
from server.utils.timeutils import to_utc_iso, utcnow_naive

router = APIRouter(prefix="/api/styles", tags=["styles"])

_TIME_RE = re.compile(r"^([01]\d|2[0-3]):[0-5]\d$")


def _validate_schedule(value: Optional[str]) -> Optional[str]:
    """Validate a style schedule JSON string.

    A schedule must be a JSON object of the form
    ``{"start": "HH:MM", "end": "HH:MM"}`` (24-hour times). Empty strings
    are normalized to None (no schedule).

    Args:
        value: The raw schedule string, or None.

    Returns:
        The validated schedule string, or None.

    Raises:
        ValueError: If the schedule is malformed.
    """
    if value is None or value.strip() == "":
        return None
    try:
        parsed = json.loads(value)
    except json.JSONDecodeError as exc:
        raise ValueError("schedule must be valid JSON") from exc
    if not isinstance(parsed, dict):
        raise ValueError('schedule must be a JSON object like {"start": "22:00", "end": "06:00"}')
    if set(parsed.keys()) != {"start", "end"}:
        raise ValueError('schedule must have exactly "start" and "end" keys')
    for key in ("start", "end"):
        time_value = parsed[key]
        if not isinstance(time_value, str) or not _TIME_RE.match(time_value):
            raise ValueError(f'schedule "{key}" must be a 24-hour "HH:MM" time string')
    return value


class StyleCreate(BaseModel):
    """Schema for creating a new style."""

    name: str = Field(min_length=1)
    prompt: str = Field(min_length=1)
    active: bool = True
    weight: float = Field(default=1.0, gt=0)
    schedule: Optional[str] = None
    tags: Optional[str] = None

    _check_schedule = field_validator("schedule")(_validate_schedule)


class StyleUpdate(BaseModel):
    """Schema for updating an existing style."""

    name: Optional[str] = Field(default=None, min_length=1)
    prompt: Optional[str] = Field(default=None, min_length=1)
    active: Optional[bool] = None
    weight: Optional[float] = Field(default=None, gt=0)
    schedule: Optional[str] = None
    tags: Optional[str] = None

    _check_schedule = field_validator("schedule")(_validate_schedule)


class StyleResponse(BaseModel):
    """Schema for style responses."""

    id: int
    name: str
    prompt: str
    active: bool
    weight: float
    schedule: Optional[str] = None
    tags: Optional[str] = None
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}

    @field_serializer("created_at", "updated_at")
    def _serialize_dt(self, value: Optional[datetime]) -> Optional[str]:
        return to_utc_iso(value)


class ReorderItem(BaseModel):
    """Schema for a single item in a reorder request."""

    id: int
    weight: float = Field(gt=0)


@router.get("", response_model=list[StyleResponse])
async def list_styles(
    session: AsyncSession = Depends(get_session),
) -> list[Style]:
    """List all styles ordered by weight descending.

    Args:
        session: Async database session.

    Returns:
        List of all styles.
    """
    result = await session.execute(select(Style).order_by(Style.weight.desc()))
    return list(result.scalars().all())


@router.post("", response_model=StyleResponse, status_code=201)
async def create_style(
    body: StyleCreate,
    session: AsyncSession = Depends(get_session),
) -> Style:
    """Create a new music style.

    Args:
        body: Style creation data.
        session: Async database session.

    Returns:
        The newly created style.
    """
    style = Style(**body.model_dump())
    session.add(style)
    await session.commit()
    await session.refresh(style)
    return style


@router.put("/{style_id}", response_model=StyleResponse)
async def update_style(
    style_id: int,
    body: StyleUpdate,
    session: AsyncSession = Depends(get_session),
) -> Style:
    """Update an existing style.

    Args:
        style_id: ID of the style to update.
        body: Fields to update.
        session: Async database session.

    Returns:
        The updated style.

    Raises:
        HTTPException: If the style is not found.
    """
    result = await session.execute(select(Style).where(Style.id == style_id))
    style = result.scalar_one_or_none()
    if style is None:
        raise HTTPException(status_code=404, detail="Style not found")

    update_data = body.model_dump(exclude_unset=True)
    for key, value in update_data.items():
        setattr(style, key, value)
    style.updated_at = utcnow_naive()

    await session.commit()
    await session.refresh(style)
    return style


@router.delete("/{style_id}")
async def delete_style(
    style_id: int,
    session: AsyncSession = Depends(get_session),
) -> dict:
    """Delete a style.

    Args:
        style_id: ID of the style to delete.
        session: Async database session.

    Returns:
        A dict confirming deletion.

    Raises:
        HTTPException: If the style is not found.
    """
    result = await session.execute(select(Style).where(Style.id == style_id))
    style = result.scalar_one_or_none()
    if style is None:
        raise HTTPException(status_code=404, detail="Style not found")

    # Explicitly clean junction rows: new DBs enforce FK cascades, but
    # pre-existing SQLite files may lack them.
    await session.execute(
        delete(show_styles).where(show_styles.c.style_id == style_id)
    )
    await session.delete(style)
    await session.commit()
    return {"success": True}


@router.post("/{style_id}/toggle", response_model=StyleResponse)
async def toggle_style(
    style_id: int,
    session: AsyncSession = Depends(get_session),
) -> Style:
    """Toggle the active state of a style.

    Args:
        style_id: ID of the style to toggle.
        session: Async database session.

    Returns:
        The updated style.

    Raises:
        HTTPException: If the style is not found.
    """
    result = await session.execute(select(Style).where(Style.id == style_id))
    style = result.scalar_one_or_none()
    if style is None:
        raise HTTPException(status_code=404, detail="Style not found")

    style.active = not style.active
    style.updated_at = utcnow_naive()
    await session.commit()
    await session.refresh(style)
    return style


@router.post("/reorder")
async def reorder_styles(
    items: list[ReorderItem],
    session: AsyncSession = Depends(get_session),
) -> dict:
    """Bulk update style weights for reordering.

    Args:
        items: List of style IDs with new weights.
        session: Async database session.

    Returns:
        A dict confirming the reorder.
    """
    for item in items:
        result = await session.execute(select(Style).where(Style.id == item.id))
        style = result.scalar_one_or_none()
        if style is not None:
            style.weight = item.weight
            style.updated_at = utcnow_naive()

    await session.commit()
    return {"success": True}
