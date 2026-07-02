"""Timezone resolution helpers for station-local scheduling.

Datetime convention (project-wide contract):
    - The database stores **naive UTC** datetimes.
    - Server code obtains "now" via :func:`utcnow_naive`.
    - API responses serialize datetimes via :func:`to_utc_iso`, which always
      includes a ``+00:00`` offset so JavaScript ``new Date()`` parses them
      as UTC rather than local time.
    - Datetimes received from clients are parsed via :func:`parse_client_dt`,
      which accepts ISO 8601 with or without an offset (no offset means UTC)
      and returns naive UTC for storage/comparison.
"""

import logging
from datetime import datetime, timezone, tzinfo
from zoneinfo import ZoneInfo

logger = logging.getLogger(__name__)


def utcnow_naive() -> datetime:
    """Return the current UTC time as a naive datetime (for DB storage)."""
    return datetime.now(timezone.utc).replace(tzinfo=None)


def to_utc_iso(dt: datetime | None) -> str | None:
    """Serialize a stored datetime as ISO 8601 with an explicit UTC offset.

    Naive datetimes are treated as UTC (the storage convention); aware
    datetimes are converted to UTC first.

    Args:
        dt: The datetime to serialize, or None.

    Returns:
        An ISO 8601 string ending in ``+00:00``, or None if ``dt`` is None.
    """
    if dt is None:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc).isoformat()


def parse_client_dt(value: str) -> datetime:
    """Parse a client-supplied ISO 8601 datetime into naive UTC.

    Strings without an offset are interpreted as UTC. A trailing ``Z`` is
    accepted.

    Args:
        value: ISO 8601 datetime string.

    Returns:
        A naive datetime in UTC, suitable for storage and comparison
        against other stored values.

    Raises:
        ValueError: If the string is not valid ISO 8601.
    """
    dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if dt.tzinfo is not None:
        dt = dt.astimezone(timezone.utc).replace(tzinfo=None)
    return dt


def resolve_timezone(tz_name: str | None) -> tzinfo:
    """Resolve an IANA timezone name to a tzinfo, falling back to UTC.

    Args:
        tz_name: IANA timezone string (e.g. "America/New_York"), or None.

    Returns:
        The resolved tzinfo, or UTC if the name is missing or invalid.
    """
    if not tz_name or tz_name.upper() == "UTC":
        return timezone.utc
    try:
        return ZoneInfo(tz_name)
    except Exception:
        logger.warning("Invalid timezone %r, falling back to UTC", tz_name)
        return timezone.utc
