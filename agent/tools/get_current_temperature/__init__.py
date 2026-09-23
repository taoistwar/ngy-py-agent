"""The ``get_current_temperature`` tool: current weather for a location.

One tool, one package, named after the tool the model sees (see ``AGENTS.md``).
The implementation lives in :mod:`~agent.tools.get_current_temperature.tool`; this
module re-exports the public surface and nothing else.
"""

from agent.tools.get_current_temperature.tool import (
    WeatherToolError,
    get_current_temperature,
)

__all__ = ["WeatherToolError", "get_current_temperature"]
