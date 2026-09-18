"""Weather related tools."""

import random
from datetime import datetime
from typing import Dict

import requests


def get_current_temperature(location: str, unit: str = "celsius") -> Dict:
    """
    Get current temperature using Open-Meteo free weather API
    No API key required - https://open-meteo.com/
    """
    try:
        # First, geocode the location to get coordinates
        geocoding_url = "https://geocoding-api.open-meteo.com/v1/search"
        geo_params = {
            "name": location,
            "count": 1,
            "language": "en",
            "format": "json",
        }

        geo_response = requests.get(geocoding_url, params=geo_params, timeout=5)
        geo_data = geo_response.json()

        if not geo_data.get("results"):
            return {
                "location": location,
                "error": f"Location '{location}' not found",
                "timestamp": datetime.now().isoformat(),
            }

        # Get coordinates from first result
        result = geo_data["results"][0]
        latitude = result["latitude"]
        longitude = result["longitude"]
        location_name = f"{result.get('name', location)}, {result.get('country', '')}"

        # Get current weather from Open-Meteo
        weather_url = "https://api.open-meteo.com/v1/forecast"

        # Determine temperature unit
        temp_unit = "fahrenheit" if unit.lower() == "fahrenheit" else "celsius"

        weather_params = {
            "latitude": latitude,
            "longitude": longitude,
            "current": "temperature_2m,relative_humidity_2m,weather_code,wind_speed_10m",
            "temperature_unit": temp_unit,
            "timezone": "auto",
        }

        weather_response = requests.get(weather_url, params=weather_params, timeout=5)
        weather_data = weather_response.json()

        if "current" not in weather_data:
            return {
                "location": location_name,
                "error": "Weather data not available",
                "timestamp": datetime.now().isoformat(),
            }

        current = weather_data["current"]

        # Map weather codes to conditions
        weather_codes = {
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

        weather_code = current.get("weather_code", 0)
        conditions = weather_codes.get(weather_code, "unknown")

        unit_symbol = "F" if unit.lower() == "fahrenheit" else "C"

        return {
            "location": location_name,
            "temperature": round(current["temperature_2m"], 1),
            "unit": unit_symbol,
            "conditions": conditions,
            "humidity": current.get("relative_humidity_2m"),
            "wind_speed": round(current.get("wind_speed_10m", 0), 1),
            "wind_unit": "km/h",
            "coordinates": {"latitude": latitude, "longitude": longitude},
            "timestamp": current.get("time", datetime.now().isoformat()),
            "source": "Open-Meteo",
        }

    except requests.RequestException as e:
        # Fallback to simulated data if API fails
        import logging

        logging.warning(f"Open-Meteo API error: {e}. Using simulated data.")

        # Simulated fallback
        base_temp = 20 + random.uniform(-10, 10)

        if unit == "fahrenheit":
            temp = base_temp * 9 / 5 + 32
            unit_symbol = "F"
        else:
            temp = base_temp
            unit_symbol = "C"

        return {
            "location": location,
            "temperature": round(temp, 1),
            "unit": unit_symbol,
            "conditions": random.choice(["sunny", "cloudy", "partly cloudy", "rainy"]),
            "timestamp": datetime.now().isoformat(),
            "note": "Simulated data (API unavailable)",
        }
    except Exception as e:
        return {
            "location": location,
            "error": str(e),
            "timestamp": datetime.now().isoformat(),
        }
