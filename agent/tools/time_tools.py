"""Clock and timezone tools."""

from datetime import datetime
from typing import Dict


def get_current_time(timezone: str = "UTC") -> Dict:
    """
    Get current date and time in specified timezone using zoneinfo (Python 3.9+)
    """
    from zoneinfo import ZoneInfo

    # Common abbreviation mappings to IANA timezone names
    timezone_aliases = {
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

    # Convert abbreviation to IANA name if needed
    tz_name = timezone_aliases.get(timezone.upper(), timezone)

    try:
        tz = ZoneInfo(tz_name)
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
    except Exception as e:
        # Fallback to UTC if timezone not found
        try:
            tz_utc = ZoneInfo("UTC")
            current_time = datetime.now(tz_utc)
            return {
                "timezone": "UTC",
                "datetime": current_time.strftime("%Y-%m-%d %H:%M:%S"),
                "date": current_time.strftime("%Y-%m-%d"),
                "time": current_time.strftime("%H:%M:%S"),
                "day_of_week": current_time.strftime("%A"),
                "utc_offset": "+0000",
                "timestamp": current_time.isoformat(),
                "note": f"Invalid timezone '{timezone}', using UTC as fallback",
            }
        except Exception as fallback_error:
            return {
                "error": str(e),
                "fallback_error": str(fallback_error),
                "timezone": timezone,
                "timestamp": datetime.utcnow().isoformat(),
            }
