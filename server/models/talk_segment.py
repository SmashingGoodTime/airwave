"""Talk segment model for generated talk show audio segments."""

from datetime import datetime, timezone

from sqlalchemy import DateTime, Float, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from server.database import Base


class TalkSegment(Base):
    """A generated talk show audio segment.

    For monologues, script_text is plain text.
    For conversations, script_text is JSON: [{"speaker": "name", "text": "line"}, ...]
    The speakers field is a JSON list of speaker names/voice IDs used.
    """

    __tablename__ = "talk_segments"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    show_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("shows.id"), nullable=True
    )
    talk_config_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("talk_show_configs.id"), nullable=True
    )
    topic_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("talk_topics.id"), nullable=True
    )
    segment_type: Mapped[str] = mapped_column(String, default="conversation")
    script_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    audio_filepath: Mapped[str | None] = mapped_column(String, nullable=True)
    duration: Mapped[float | None] = mapped_column(Float, nullable=True)
    speakers: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(String, default="generating")
    context: Mapped[str | None] = mapped_column(Text, nullable=True)
    loudness_lufs: Mapped[float | None] = mapped_column(Float, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=lambda: datetime.now(timezone.utc)
    )
    played_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
