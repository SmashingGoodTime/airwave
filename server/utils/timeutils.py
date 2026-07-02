"""Timezone resolution helpers for station-local scheduling."""

import logging
from datetime import timezone, tzinfo
from zoneinfo import ZoneInfo

logger = logging.getLogger(__name__)


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
