"""DJ configuration model for station personality settings."""

from datetime import datetime

from sqlalchemy import Boolean, DateTime, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from server.database import Base
from server.utils.timeutils import utcnow_naive


class DJConfig(Base):
    """Configuration for the AI DJ personality and behavior.

    Multiple configs can exist. One is marked as the station default
    via ``is_default``. Shows may link to a specific config via
    ``Show.dj_config_id``; when unset the default is used.
    """

    __tablename__ = "dj_configs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String, default="Default")
    is_default: Mapped[bool] = mapped_column(Boolean, default=False)
    station_name: Mapped[str] = mapped_column(String, default="AI Radio")
    dj_name: Mapped[str] = mapped_column(String, default="DJ Claude")
    personality_prompt: Mapped[str | None] = mapped_column(Text, nullable=True)
    voice_provider: Mapped[str | None] = mapped_column(String, nullable=True)
    voice_id: Mapped[str | None] = mapped_column(String, nullable=True)
    voice_settings: Mapped[str | None] = mapped_column(Text, nullable=True)
    break_frequency: Mapped[int] = mapped_column(Integer, default=3)
    break_frequency_variance: Mapped[int] = mapped_column(Integer, default=1)
    mention_time: Mapped[bool] = mapped_column(Boolean, default=True)
    mention_weather: Mapped[bool] = mapped_column(Boolean, default=False)
    content_policy: Mapped[str] = mapped_column(String, default="clean_vocals")
    content_policy_suffix: Mapped[str | None] = mapped_column(Text, nullable=True)
    max_break_duration: Mapped[int] = mapped_column(Integer, default=60)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=utcnow_naive, onupdate=utcnow_naive
    )
