"""Style management API endpoints."""

from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from server.database import get_session
from server.models.style import Style

router = APIRouter(prefix="/api/styles", tags=["styles"])


class StyleCreate(BaseModel):
    """Schema for creating a new style."""

    name: str = Field(min_length=1)
    prompt: str = Field(min_length=1)
    active: bool = True
    weight: float = Field(default=1.0, gt=0)
    schedule: Optional[str] = None
    tags: Optional[str] = None


class StyleUpdate(BaseModel):
    """Schema for updating an existing style."""

    name: Optional[str] = Field(default=None, min_length=1)
    prompt: Optional[str] = Field(default=None, min_length=1)
    active: Optional[bool] = None
    weight: Optional[float] = Field(default=None, gt=0)
    schedule: Optional[str] = None
    tags: Optional[str] = None


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
    style.updated_at = datetime.now(timezone.utc)

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
    style.updated_at = datetime.now(timezone.utc)
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
            style.updated_at = datetime.now(timezone.utc)

    await session.commit()
    return {"success": True}
