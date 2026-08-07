"""Audio asset model for immutable normalized audio metadata."""

from datetime import datetime

from sqlalchemy import DateTime, Float, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from server.database import Base
from server.utils.timeutils import utcnow_naive


class AudioAsset(Base):
    """An immutable audio file prepared for station playout.

    Generated tracks, DJ breaks, calls, and fallback loops can all
    reference this common asset record once normalized.
    """

    __tablename__ = "audio_assets"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    asset_type: Mapped[str] = mapped_column(String, nullable=False)
    original_filepath: Mapped[str | None] = mapped_column(String, nullable=True)
    normalized_filepath: Mapped[str | None] = mapped_column(String, nullable=True)
    duration: Mapped[float | None] = mapped_column(Float, nullable=True)
    loudness_lufs: Mapped[float | None] = mapped_column(Float, nullable=True)
    sample_rate: Mapped[int | None] = mapped_column(Integer, nullable=True)
    channels: Mapped[int | None] = mapped_column(Integer, nullable=True)
    checksum: Mapped[str | None] = mapped_column(String, nullable=True)
    provider: Mapped[str | None] = mapped_column(String, nullable=True)
    status: Mapped[str] = mapped_column(String, default="ready")
    metadata_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow_naive)
