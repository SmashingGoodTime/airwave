"""Track model representing a generated music track."""

import uuid
from datetime import datetime

from sqlalchemy import DateTime, Float, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from server.database import Base
from server.utils.timeutils import utcnow_naive


class Track(Base):
    """A generated music track in the radio station library."""

    __tablename__ = "tracks"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    uuid: Mapped[str] = mapped_column(
        String(36), unique=True, default=lambda: str(uuid.uuid4())
    )
    filepath: Mapped[str | None] = mapped_column(String, nullable=True)
    title: Mapped[str | None] = mapped_column(String, nullable=True)
    style_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("styles.id", ondelete="SET NULL"), nullable=True, index=True
    )
    style_prompt: Mapped[str | None] = mapped_column(Text, nullable=True)
    content_policy_suffix: Mapped[str | None] = mapped_column(Text, nullable=True)
    duration: Mapped[float | None] = mapped_column(Float, nullable=True)
    provider: Mapped[str | None] = mapped_column(String, nullable=True)
    status: Mapped[str] = mapped_column(String, default="generating", index=True)
    loudness_lufs: Mapped[float | None] = mapped_column(Float, nullable=True)
    lyrics: Mapped[str | None] = mapped_column(Text, nullable=True)
    metadata_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow_naive)
    # When the track was last pushed to the playout queue. Cleanup uses this
    # (not created_at, which is generation time) to detect orphaned "queued"
    # rows, since prefilled tracks can be arbitrarily old when queued.
    queued_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    played_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
