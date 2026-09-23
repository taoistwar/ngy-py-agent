"""The ``get_current_time`` spec: name, schema and permission kind."""

from agent.tools.bindings import ToolBindings
from agent.tools.get_current_time.tool import get_current_time
from agent.tools.spec import ToolSpec

NAME = "get_current_time"


def build_spec(bindings: ToolBindings) -> ToolSpec:
    """Declare the tool; the bindings are ignored because it needs no workspace."""
    return ToolSpec(
        name=NAME,
        handler=get_current_time,
        description="Get the current date and time in a specific timezone",
        parameters={
            "type": "object",
            "properties": {
                "timezone": {
                    "type": "string",
                    "description": (
                        "Timezone name (e.g., 'America/New_York', 'Europe/London', 'Asia/Tokyo'). "
                        "Use standard IANA timezone names."
                    ),
                    "default": "UTC",
                }
            },
            "required": [],
        },
    )
