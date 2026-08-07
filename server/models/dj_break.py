"""DJ Break model for generated DJ speech segments."""

from datetime import datetime

from sqlalchemy import DateTime, Float, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from server.database import Base
from server.utils.timeutils import utcnow_naive


class DJBreak(Base):
    """A generated DJ break segment with script and audio."""

    __tablename__ = "dj_breaks"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    script_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    audio_filepath: Mapped[str | None] = mapped_column(String, nullable=True)
    context: Mapped[str | None] = mapped_column(Text, nullable=True)
    duration: Mapped[float | None] = mapped_column(Float, nullable=True)
    status: Mapped[str] = mapped_column(String, default="generating")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow_naive)
    played_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
