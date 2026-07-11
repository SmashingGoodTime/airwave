"""Station model for global station configuration."""

from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Mapped, mapped_column

from server.database import Base


class Station(Base):
    """Global station configuration and status."""

    __tablename__ = "stations"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    timezone: Mapped[str] = mapped_column(String, default="UTC")
    stream_url: Mapped[str | None] = mapped_column(String, nullable=True)
    setup_complete: Mapped[bool] = mapped_column(Boolean, default=False)
    disk_retention_days: Mapped[int] = mapped_column(Integer, default=30)
    buffer_target: Mapped[int] = mapped_column(Integer, default=5)
    buffer_warning_threshold: Mapped[int] = mapped_column(Integer, default=2)
    recording_enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    recording_retention_days: Mapped[int] = mapped_column(Integer, default=7)

    # Broadcast state columns
    broadcast_mode: Mapped[str] = mapped_column(String, default="manual")  # manual or scheduled
    current_show_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("shows.id", ondelete="SET NULL"), nullable=True
    )
    current_show_started_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)


async def get_station(session: AsyncSession) -> Station | None:
    """Return the singleton Station row (lowest id), or None if absent.

    The station table holds exactly one row in practice; this helper is
    the single place that query lives.

    Args:
        session: Async database session.

    Returns:
        The Station row, or None before first-run initialization.
    """
    result = await session.execute(
        select(Station).order_by(Station.id).limit(1)
    )
    return result.scalar_one_or_none()
