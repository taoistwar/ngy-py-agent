"""Tests for the live weather tool.

Run from the repository root::

    uv run python test/tools/weather_tools_test.py -v
"""

import sys
import unittest
from pathlib import Path
from unittest import mock

import requests

# ``test/`` is intentionally not a package, so the repository root is added to
# the import path here instead of adding a ``test/__init__.py``.
_REPO_ROOT = Path(__file__).resolve().parents[2]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from agent.tools.weather_tools import (  # noqa: E402
    WeatherToolError,
    get_current_temperature,
)

_PARIS_MATCH = {
    "results": [
        {"name": "Paris", "country": "France", "latitude": 48.85, "longitude": 2.35}
    ]
}

_PARIS_CURRENT = {
    "current": {
        "time": "2026-09-18T12:00",
        "temperature_2m": 18.34,
        "relative_humidity_2m": 61,
        "weather_code": 61,
        "wind_speed_10m": 11.2,
    }
}


def _fake_response(payload):
    response = mock.MagicMock()
    response.json.return_value = payload
    response.raise_for_status.return_value = None
    return response


def _ok_responses():
    return [_fake_response(_PARIS_MATCH), _fake_response(_PARIS_CURRENT)]


class GetCurrentTemperatureTest(unittest.TestCase):
    def setUp(self):
        patcher = mock.patch("agent.tools.weather_tools.requests.get")
        self.get = patcher.start()
        self.addCleanup(patcher.stop)

    def test_returns_live_reading(self):
        self.get.side_effect = _ok_responses()

        result = get_current_temperature("Paris, France")

        self.assertEqual(result["location"], "Paris, France")
        self.assertEqual(result["temperature"], 18.3)
        self.assertEqual(result["unit"], "C")
        self.assertEqual(result["conditions"], "light rain")
        self.assertEqual(result["humidity"], 61)
        self.assertEqual(result["source"], "Open-Meteo")
        self.assertNotIn("note", result)

    def test_requests_fahrenheit_when_asked(self):
        self.get.side_effect = _ok_responses()

        result = get_current_temperature("Paris, France", unit="fahrenheit")

        self.assertEqual(result["unit"], "F")
        self.assertEqual(self.get.call_args_list[1].kwargs["params"]["temperature_unit"], "fahrenheit")

    def test_unknown_location_raises_instead_of_faking(self):
        self.get.side_effect = [_fake_response({"results": []})]

        with self.assertRaises(WeatherToolError) as ctx:
            get_current_temperature("Nowhere City")

        self.assertIn("not found", str(ctx.exception))

    def test_network_failure_raises_instead_of_faking(self):
        self.get.side_effect = requests.ConnectionError("connection refused")

        with self.assertRaises(WeatherToolError) as ctx:
            get_current_temperature("Paris, France")

        self.assertIn("Open-Meteo request failed", str(ctx.exception))

    def test_http_error_raises(self):
        response = mock.MagicMock()
        response.raise_for_status.side_effect = requests.HTTPError("502 Bad Gateway")
        self.get.return_value = response

        with self.assertRaises(WeatherToolError):
            get_current_temperature("Paris, France")

    def test_broken_json_raises(self):
        response = mock.MagicMock()
        response.raise_for_status.return_value = None
        response.json.side_effect = ValueError("Expecting value")
        self.get.return_value = response

        with self.assertRaises(WeatherToolError) as ctx:
            get_current_temperature("Paris, France")

        self.assertIn("not valid JSON", str(ctx.exception))

    def test_missing_current_block_raises(self):
        self.get.side_effect = [_fake_response(_PARIS_MATCH), _fake_response({})]

        with self.assertRaises(WeatherToolError) as ctx:
            get_current_temperature("Paris, France")

        self.assertIn("not available", str(ctx.exception))


if __name__ == "__main__":
    unittest.main()
