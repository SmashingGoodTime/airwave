"""Play log API endpoints for playback history."""

import csv
import io
import json
from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends, Query
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from server.database import get_session
from server.models.playlog import PlayLog

router = APIRouter(prefix="/api/playlog", tags=["playlog"])


class PlayLogResponse(BaseModel):
    """Schema for play log responses."""

    id: int
    item_type: str
    item_id: int
    started_at: datetime
    ended_at: Optional[datetime] = None
    duration: Optional[float] = None
    metadata_json: Optional[str] = None
    title: Optional[str] = None

    model_config = {"from_attributes": True}


def _enrich_response(item: PlayLog) -> PlayLogResponse:
    """Create a PlayLogResponse from a PlayLog, extracting title from metadata."""
    resp = PlayLogResponse.model_validate(item)
    if item.metadata_json:
        try:
            meta = json.loads(item.metadata_json)
            resp.title = meta.get("title") or meta.get("show") or None
        except (json.JSONDecodeError, TypeError):
            pass
    return resp


class PaginatedPlayLogs(BaseModel):
    """Schema for paginated play log responses."""

    items: list[PlayLogResponse]
    total: int
    page: int
    per_page: int


@router.get("", response_model=PaginatedPlayLogs)
async def list_play_logs(
    page: int = Query(1, ge=1),
    per_page: int = Query(50, ge=1, le=200),
    start_date: Optional[str] = Query(None, description="Filter from date (ISO format)"),
    end_date: Optional[str] = Query(None, description="Filter to date (ISO format)"),
    session: AsyncSession = Depends(get_session),
) -> PaginatedPlayLogs:
    """List play logs with pagination and optional date range filter.

    Args:
        page: Page number (1-indexed).
        per_page: Number of items per page.
        start_date: Optional start date filter (ISO format).
        end_date: Optional end date filter (ISO format).
        session: Async database session.

    Returns:
        Paginated list of play logs with total count.
    """
    # Build base query with optional date filters
    filters = []
    if start_date:
        try:
            start_dt = datetime.fromisoformat(start_date)
            filters.append(PlayLog.started_at >= start_dt)
        except ValueError:
            pass
    if end_date:
        try:
            end_dt = datetime.fromisoformat(end_date)
            filters.append(PlayLog.started_at <= end_dt)
        except ValueError:
            pass

    count_query = select(func.count(PlayLog.id))
    if filters:
        count_query = count_query.where(*filters)
    count_result = await session.execute(count_query)
    total = count_result.scalar_one()

    offset = (page - 1) * per_page
    query = select(PlayLog).order_by(PlayLog.started_at.desc()).offset(offset).limit(per_page)
    if filters:
        query = query.where(*filters)
    result = await session.execute(query)
    items = list(result.scalars().all())

    return PaginatedPlayLogs(
        items=[_enrich_response(item) for item in items],
        total=total,
        page=page,
        per_page=per_page,
    )


@router.get("/export")
async def export_play_logs(
    session: AsyncSession = Depends(get_session),
) -> StreamingResponse:
    """Export all play logs as a CSV file.

    Args:
        session: Async database session.

    Returns:
        A streaming CSV response with all play log records.
    """
    result = await session.execute(
        select(PlayLog).order_by(PlayLog.started_at.desc())
    )
    logs = result.scalars().all()

    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(
        ["id", "item_type", "item_id", "started_at", "ended_at", "duration", "metadata"]
    )
    for log in logs:
        writer.writerow([
            log.id,
            log.item_type,
            log.item_id,
            log.started_at.isoformat() if log.started_at else "",
            log.ended_at.isoformat() if log.ended_at else "",
            log.duration or "",
            log.metadata_json or "",
        ])

    output.seek(0)
    return StreamingResponse(
        iter([output.getvalue()]),
        media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=playlog.csv"},
    )
