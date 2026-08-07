"""Show model representing a scheduled broadcast block."""

from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from server.database import Base
from server.utils.timeutils import utcnow_naive


class Show(Base):
    """A program block representing a show with a specific configuration and duration.

    Shows determine station behavior when in scheduled mode.
    The station transitions from show to show in queue_order, playing each for duration_minutes.
    When in manual mode, a single show config is played indefinitely.
    """

    __tablename__ = "shows"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String, nullable=False)
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    duration_minutes: Mapped[int] = mapped_column(Integer, default=30)
    queue_order: Mapped[int] = mapped_column(Integer, default=0)
    dj_config_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("dj_configs.id", ondelete="SET NULL"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow_naive)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=utcnow_naive, onupdate=utcnow_naive
    )
