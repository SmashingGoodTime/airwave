"""Talk show configuration model for host, co-host, and segment settings."""

from datetime import datetime, timezone

from sqlalchemy import Boolean, DateTime, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from server.database import Base


class TalkShowConfig(Base):
    """Configuration for a talk show including host voices and segment rules.

    The cohost_voices field stores a JSON list of co-host definitions:
    [{"name": "...", "voice_id": "...", "voice_settings": {...}, "personality_prompt": "..."}]
    """

    __tablename__ = "talk_show_configs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String, nullable=False)
    host_voice_id: Mapped[str | None] = mapped_column(String, nullable=True)
    host_voice_settings: Mapped[str | None] = mapped_column(Text, nullable=True)
    host_personality_prompt: Mapped[str | None] = mapped_column(Text, nullable=True)
    cohost_voices: Mapped[str | None] = mapped_column(Text, nullable=True)
    segment_min_duration: Mapped[int] = mapped_column(Integer, default=120)
    segment_max_duration: Mapped[int] = mapped_column(Integer, default=600)
    segment_gap: Mapped[int] = mapped_column(Integer, default=5)
    topic_rotation: Mapped[str] = mapped_column(String, default="weighted")
    max_speakers: Mapped[int] = mapped_column(Integer, default=3)
    allow_call_ins: Mapped[bool] = mapped_column(Boolean, default=False)
    intro_style: Mapped[str | None] = mapped_column(
        Text, nullable=True,
        doc="How to open segments: 'energetic', 'casual', 'dramatic', or custom text"
    )
    outro_style: Mapped[str | None] = mapped_column(
        Text, nullable=True,
        doc="How to close segments: 'tease_next', 'recap', 'cliffhanger', or custom text"
    )
    conversation_style: Mapped[str | None] = mapped_column(
        Text, nullable=True,
        doc="Additional style guidance for conversations: 'comedic', 'intellectual', 'storytelling'"
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=lambda: datetime.now(timezone.utc)
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime,
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )
