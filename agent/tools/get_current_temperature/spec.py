"""The ``get_current_temperature`` spec: name, schema and permission kind."""

from agent.tools.bindings import ToolBindings
from agent.tools.get_current_temperature.tool import get_current_temperature
from agent.tools.spec import ToolSpec

NAME = "get_current_temperature"


def build_spec(bindings: ToolBindings) -> ToolSpec:
    """Declare the tool; the bindings are ignored because it needs no workspace."""
    return ToolSpec(
        name=NAME,
        handler=get_current_temperature,
        description="Get the current temperature for a specific location",
        parameters={
            "type": "object",
            "properties": {
                "location": {
                    "type": "string",
                    "description": "The city and country, e.g., 'Paris, France'",
                },
                "unit": {
                    "type": "string",
                    "enum": ["celsius", "fahrenheit"],
                    "description": "The temperature unit to use (by default, celsius)",
                },
            },
            "required": ["location", "unit"],
        },
    )
