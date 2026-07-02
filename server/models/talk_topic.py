"""Talk topic model for talk show discussion subjects."""

from datetime import datetime, timezone

from sqlalchemy import Boolean, DateTime, Float, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from server.database import Base


class TalkTopic(Base):
    """A topic or discussion subject for a talk show segment.

    Topics can be monologues (single host), conversations (multiple speakers),
    debates, or interviews. The weight field controls selection probability
    when using weighted rotation.
    """

    __tablename__ = "talk_topics"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    talk_config_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("talk_show_configs.id"), nullable=False
    )
    title: Mapped[str] = mapped_column(String, nullable=False)
    prompt: Mapped[str] = mapped_column(Text, nullable=False)
    topic_type: Mapped[str] = mapped_column(String, default="conversation")
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    weight: Mapped[float] = mapped_column(Float, default=1.0)
    play_count: Mapped[int] = mapped_column(Integer, default=0)
    max_plays: Mapped[int | None] = mapped_column(Integer, nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=lambda: datetime.now(timezone.utc)
    )
