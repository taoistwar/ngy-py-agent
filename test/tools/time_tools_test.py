"""Tests for the timezone aware clock tool.

Run from the repository root::

    uv run python test/tools/time_tools_test.py -v
"""

import sys
import unittest
from pathlib import Path

# ``test/`` is intentionally not a package, so the repository root is added to
# the import path here instead of adding a ``test/__init__.py``.
_REPO_ROOT = Path(__file__).resolve().parents[2]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from agent.tools.time_tools import (  # noqa: E402
    TimeToolError,
    get_current_time,
)


class GetCurrentTimeTest(unittest.TestCase):
    def test_defaults_to_utc(self):
        result = get_current_time()

        self.assertEqual(result["timezone"], "UTC")
        self.assertEqual(result["utc_offset"], "+0000")

    def test_resolves_abbreviation_alias(self):
        result = get_current_time("JST")

        self.assertEqual(result["timezone"], "Asia/Tokyo")
        self.assertEqual(result["utc_offset"], "+0900")

    def test_accepts_iana_name(self):
        result = get_current_time("Asia/Shanghai")

        self.assertEqual(result["timezone"], "Asia/Shanghai")
        self.assertEqual(result["utc_offset"], "+0800")

    def test_alias_lookup_is_case_insensitive(self):
        result = get_current_time("jst")

        self.assertEqual(result["timezone"], "Asia/Tokyo")

    def test_reports_requested_zone_not_a_silent_utc_fallback(self):
        result = get_current_time("Europe/Paris")

        self.assertEqual(result["timezone"], "Europe/Paris")
        self.assertNotIn("note", result)

    def test_unknown_timezone_raises(self):
        with self.assertRaises(TimeToolError) as ctx:
            get_current_time("Mars/Olympus")

        self.assertIn("Unknown timezone 'Mars/Olympus'", str(ctx.exception))

    def test_missing_timezone_raises(self):
        with self.assertRaises(TimeToolError):
            get_current_time(None)


if __name__ == "__main__":
    unittest.main()
