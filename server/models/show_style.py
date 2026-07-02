"""Many-to-many junction table linking shows to music styles."""

from sqlalchemy import Column, ForeignKey, Integer, Table

from server.database import Base

show_styles = Table(
    "show_styles",
    Base.metadata,
    Column("show_id", Integer, ForeignKey("shows.id", ondelete="CASCADE"), primary_key=True),
    Column("style_id", Integer, ForeignKey("styles.id", ondelete="CASCADE"), primary_key=True),
)
