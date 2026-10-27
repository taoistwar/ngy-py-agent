"""The ``get_current_temperature`` spec: name, schema and permission kind."""

from agent.tools.bindings import ToolBindings
from agent.tools.get_current_temperature.i18n import DE, FR, RU, ZH_CN, ZH_TW
from agent.tools.get_current_temperature.tool import get_current_temperature
from agent.tools.spec import CATEGORY_LOOKUP, ToolSpec, localized_texts

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
        category=CATEGORY_LOOKUP,
        description_i18n=localized_texts(zh_cn=ZH_CN, zh_tw=ZH_TW, fr=FR, de=DE, ru=RU),
    )
