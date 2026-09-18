"""Weather related tools.

Live readings come from the free Open-Meteo API (no API key required):
https://open-meteo.com/

Every failure is surfaced as :class:`WeatherToolError` instead of a fabricated
reading, so callers can never mistake made-up data for a real measurement.
"""

from datetime import datetime
from typing import Dict

import requests

GEOCODING_URL = "https://geocoding-api.open-meteo.com/v1/search"
FORECAST_URL = "https://api.open-meteo.com/v1/forecast"
REQUEST_TIMEOUT_SECONDS = 5

# WMO weather interpretation codes returned by Open-Meteo.
WEATHER_CODES: Dict[int, str] = {
    0: "clear sky",
    1: "mainly clear",
    2: "partly cloudy",
    3: "overcast",
    45: "foggy",
    48: "foggy",
    51: "light drizzle",
    53: "moderate drizzle",
    55: "dense drizzle",
    61: "light rain",
    63: "moderate rain",
    65: "heavy rain",
    71: "light snow",
    73: "moderate snow",
    75: "heavy snow",
    77: "snow grains",
    80: "light rain showers",
    81: "moderate rain showers",
    82: "heavy rain showers",
    85: "light snow showers",
    86: "heavy snow showers",
    95: "thunderstorm",
    96: "thunderstorm with light hail",
    99: "thunderstorm with heavy hail",
}


class WeatherToolError(RuntimeError):
    """Raised when a live weather reading cannot be retrieved."""


def get_current_temperature(location: str, unit: str = "celsius") -> Dict:
    """
    Get current temperature using Open-Meteo free weather API
    No API key required - https://open-meteo.com/
    """
    unit_symbol = _unit_symbol(unit)
    temperature_unit = "fahrenheit" if unit_symbol == "F" else "celsius"

    match = _geocode(location)
    latitude = match["latitude"]
    longitude = match["longitude"]
    location_name = _display_name(match, location)

    current = _fetch_current(latitude, longitude, temperature_unit, location_name)

    return {
        "location": location_name,
        "temperature": round(current["temperature_2m"], 1),
        "unit": unit_symbol,
        "conditions": WEATHER_CODES.get(current.get("weather_code", 0), "unknown"),
        "humidity": current.get("relative_humidity_2m"),
        "wind_speed": round(current.get("wind_speed_10m", 0), 1),
        "wind_unit": "km/h",
        "coordinates": {"latitude": latitude, "longitude": longitude},
        "timestamp": current.get("time", datetime.now().isoformat()),
        "source": "Open-Meteo",
    }


def _unit_symbol(unit: str) -> str:
    return "F" if str(unit).lower() == "fahrenheit" else "C"


def _display_name(match: Dict, fallback: str) -> str:
    return ", ".join(part for part in (match.get("name", fallback), match.get("country")) if part)


def _geocode(location: str) -> Dict:
    """Resolve a place name to its first Open-Meteo geocoding match."""
    payload = _get_json(
        GEOCODING_URL,
        {
            "name": location,
            "count": 1,
            "language": "en",
            "format": "json",
        },
        describe=f"geocoding '{location}'",
    )

    results = payload.get("results") or []
    if not results:
        raise WeatherToolError(f"Location '{location}' not found")
    return results[0]


def _fetch_current(
    latitude: float,
    longitude: float,
    temperature_unit: str,
    location_name: str,
) -> Dict:
    """Fetch the current observation block for the resolved coordinates."""
    payload = _get_json(
        FORECAST_URL,
        {
            "latitude": latitude,
            "longitude": longitude,
            "current": "temperature_2m,relative_humidity_2m,weather_code,wind_speed_10m",
            "temperature_unit": temperature_unit,
            "timezone": "auto",
        },
        describe=f"weather for '{location_name}'",
    )

    current = payload.get("current")
    if not current or "temperature_2m" not in current:
        raise WeatherToolError(f"Weather data not available for '{location_name}'")
    return current


def _get_json(url: str, params: Dict, describe: str) -> Dict:
    """GET ``url`` and return parsed JSON, raising WeatherToolError on any failure."""
    try:
        response = requests.get(url, params=params, timeout=REQUEST_TIMEOUT_SECONDS)
        response.raise_for_status()
        payload = response.json()
    except requests.RequestException as exc:
        raise WeatherToolError(f"Open-Meteo request failed while {describe}: {exc}") from exc
    except ValueError as exc:
        raise WeatherToolError(
            f"Open-Meteo response was not valid JSON while {describe}: {exc}"
        ) from exc

    if not isinstance(payload, dict):
        raise WeatherToolError(f"Open-Meteo returned an unexpected payload while {describe}")
    return payload
