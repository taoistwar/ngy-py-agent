"""Clock and timezone tools.

Timezone resolution uses the IANA database through :mod:`zoneinfo`. Platforms
without a system tz database (notably Windows) need the ``tzdata`` package,
which is already pulled in transitively by ``pydantic[timezone]``.

An unknown timezone raises :class:`TimeToolError`; silently answering with UTC
would look like a successful lookup in the caller's own timezone.
"""

from datetime import datetime
from typing import Dict
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

# Common abbreviation mappings to IANA timezone names
TIMEZONE_ALIASES = {
    "EST": "America/New_York",
    "EDT": "America/New_York",
    "PST": "America/Los_Angeles",
    "PDT": "America/Los_Angeles",
    "CST": "America/Chicago",
    "CDT": "America/Chicago",
    "MST": "America/Denver",
    "MDT": "America/Denver",
    "GMT": "Europe/London",
    "BST": "Europe/London",
    "CET": "Europe/Paris",
    "CEST": "Europe/Paris",
    "JST": "Asia/Tokyo",
    "IST": "Asia/Kolkata",
    "AEST": "Australia/Sydney",
    "AEDT": "Australia/Sydney",
    "SGT": "Asia/Singapore",
    "HKT": "Asia/Hong_Kong",
    "UTC+1": "Etc/GMT-1",  # Note: signs are inverted in Etc/GMT
    "UTC-1": "Etc/GMT+1",
    "UTC+8": "Etc/GMT-8",
    "UTC-8": "Etc/GMT+8",
}


class TimeToolError(RuntimeError):
    """Raised when the requested timezone cannot be resolved."""


def get_current_time(timezone: str = "UTC") -> Dict:
    """
    Get current date and time in specified timezone using zoneinfo (Python 3.9+)
    """
    tz_name = TIMEZONE_ALIASES.get(str(timezone).upper(), str(timezone))

    try:
        tz = ZoneInfo(tz_name)
    except (ZoneInfoNotFoundError, ValueError) as exc:
        raise TimeToolError(
            f"Unknown timezone '{timezone}' (resolved to '{tz_name}')"
        ) from exc

    current_time = datetime.now(tz)

    return {
        "timezone": tz_name,
        "datetime": current_time.strftime("%Y-%m-%d %H:%M:%S"),
        "date": current_time.strftime("%Y-%m-%d"),
        "time": current_time.strftime("%H:%M:%S"),
        "day_of_week": current_time.strftime("%A"),
        "utc_offset": current_time.strftime("%z"),
        "timestamp": current_time.isoformat(),
    }
