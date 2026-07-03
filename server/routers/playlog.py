"""Play log API endpoints for playback history."""

import csv
import io
import json
from collections.abc import AsyncGenerator
from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, field_serializer
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from server.database import get_session, get_session_factory
from server.models.playlog import PlayLog
from server.utils.timeutils import parse_client_dt, to_utc_iso

router = APIRouter(prefix="/api/playlog", tags=["playlog"])

# Rows fetched per query while streaming the CSV export.
EXPORT_BATCH_SIZE = 500


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

    @field_serializer("started_at", "ended_at")
    def _serialize_dt(self, value: Optional[datetime]) -> Optional[str]:
        return to_utc_iso(value)


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


def _parse_date_filter(value: str, param_name: str) -> datetime:
    """Parse a client-supplied date filter into naive UTC.

    Args:
        value: ISO 8601 datetime string from the query.
        param_name: Query parameter name (for the error message).

    Returns:
        A naive UTC datetime comparable against stored values.

    Raises:
        HTTPException: 422 if the value is not valid ISO 8601.
    """
    try:
        return parse_client_dt(value)
    except ValueError as exc:
        raise HTTPException(
            status_code=422,
            detail=f"Invalid {param_name}: {value!r} is not a valid ISO 8601 datetime",
        ) from exc


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

    Raises:
        HTTPException: 422 if a date filter is not valid ISO 8601.
    """
    # Build base query with optional date filters
    filters = []
    if start_date:
        filters.append(PlayLog.started_at >= _parse_date_filter(start_date, "start_date"))
    if end_date:
        filters.append(PlayLog.started_at <= _parse_date_filter(end_date, "end_date"))

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


def _csv_safe(value: str) -> str:
    """Guard a text cell against spreadsheet formula injection.

    Cells starting with ``=``, ``+``, ``-``, ``@``, or a tab are prefixed
    with a single quote so spreadsheet apps treat them as text.

    Args:
        value: The raw cell text.

    Returns:
        The guarded cell text.
    """
    if value and value[0] in ("=", "+", "-", "@", "\t"):
        return "'" + value
    return value


async def _generate_csv() -> AsyncGenerator[str, None]:
    """Stream play log rows as CSV lines, fetching in batches.

    Opens its own session because FastAPI dependency sessions close before
    a StreamingResponse body is generated. Rows are keyset-paginated by id
    (ascending, i.e. chronological) so memory stays bounded.

    Yields:
        CSV-formatted lines including the header.
    """
    buffer = io.StringIO()
    writer = csv.writer(buffer)

    def _row(values: list) -> str:
        writer.writerow(values)
        line = buffer.getvalue()
        buffer.seek(0)
        buffer.truncate(0)
        return line

    yield _row(
        ["id", "item_type", "item_id", "started_at", "ended_at", "duration", "metadata"]
    )

    factory = get_session_factory()
    async with factory() as session:
        last_id = 0
        while True:
            result = await session.execute(
                select(PlayLog)
                .where(PlayLog.id > last_id)
                .order_by(PlayLog.id)
                .limit(EXPORT_BATCH_SIZE)
            )
            batch = result.scalars().all()
            if not batch:
                break
            for log in batch:
                yield _row([
                    log.id,
                    _csv_safe(log.item_type or ""),
                    log.item_id,
                    to_utc_iso(log.started_at) or "",
                    to_utc_iso(log.ended_at) or "",
                    log.duration or "",
                    _csv_safe(log.metadata_json or ""),
                ])
            last_id = batch[-1].id


@router.get("/export")
async def export_play_logs() -> StreamingResponse:
    """Export all play logs as a CSV file.

    Returns:
        A streaming CSV response with all play log records.
    """
    return StreamingResponse(
        _generate_csv(),
        media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=playlog.csv"},
    )
