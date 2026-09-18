"""Declarative specifications for the built-in tools.

Each :class:`ToolSpec` binds a model-facing name and JSON schema to the callable
that implements it. ``ToolRegistry`` consumes these specs, so adding a tool means
adding one entry here plus the implementation module next to it.
"""

from dataclasses import dataclass
from typing import Any, Callable, Dict, Optional, Sequence

from agent.tools import code_tools, file_tools, finance_tools, time_tools, weather_tools


@dataclass(frozen=True)
class ToolSpec:
    """A single tool exposed to the language model."""

    name: str
    handler: Callable[..., Any]
    description: str
    parameters: Dict[str, Any]


SPEC_GET_CURRENT_TEMPERATURE = ToolSpec(
    name="get_current_temperature",
    handler=weather_tools.get_current_temperature,
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

SPEC_GET_CURRENT_TIME = ToolSpec(
    name="get_current_time",
    handler=time_tools.get_current_time,
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

SPEC_CONVERT_CURRENCY = ToolSpec(
    name="convert_currency",
    handler=finance_tools.convert_currency,
    description=(
        "Convert an amount from one currency to another. You MUST use this tool to convert "
        "currencies in order to get the latest exchange rate."
    ),
    parameters={
        "type": "object",
        "properties": {
            "amount": {"type": "number", "description": "Amount to convert"},
            "from_currency": {
                "type": "string",
                "description": "Source currency code (e.g., 'USD', 'EUR')",
            },
            "to_currency": {
                "type": "string",
                "description": "Target currency code (e.g., 'USD', 'EUR')",
            },
        },
        "required": ["amount", "from_currency", "to_currency"],
    },
)

SPEC_CODE_INTERPRETER = ToolSpec(
    name="code_interpreter",
    handler=code_tools.code_interpreter,
    description=(
        "Execute Python code for calculations and data processing. You MUST use this tool to "
        "perform any complex calculations or data processing."
    ),
    parameters={
        "type": "object",
        "properties": {
            "code": {
                "type": "string",
                "description": (
                    "Python code to execute. Use Python operators: ** for exponentiation "
                    "(2 ** 10), not ^. In Python, ^ is bitwise XOR."
                ),
            }
        },
        "required": ["code"],
    },
)

READ_FILE_TOOL_NAME = "read_file"


def build_read_file_spec(
    base_dir: Optional[str] = None,
    max_tokens: int = 0,
    provider: str = "",
    model: str = "",
) -> ToolSpec:
    """Build the workspace scoped read tool, bound to a workspace root."""
    return ToolSpec(
        name=READ_FILE_TOOL_NAME,
        handler=file_tools.make_read_file_tool(
            base_dir=base_dir,
            max_tokens=max_tokens,
            provider=provider,
            model=model,
        ),
        description=file_tools.READ_FILE_DESCRIPTION,
        parameters=file_tools.READ_FILE_PARAMETERS,
    )


DEFAULT_TOOL_SPECS: Sequence[ToolSpec] = (
    SPEC_GET_CURRENT_TEMPERATURE,
    SPEC_GET_CURRENT_TIME,
    SPEC_CONVERT_CURRENCY,
    SPEC_CODE_INTERPRETER,
)
