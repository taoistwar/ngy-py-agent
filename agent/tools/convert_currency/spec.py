"""The ``convert_currency`` spec: name, schema and permission kind."""

from agent.tools.bindings import ToolBindings
from agent.tools.convert_currency.i18n import DE, FR, RU, ZH_CN, ZH_TW
from agent.tools.convert_currency.tool import convert_currency
from agent.tools.spec import CATEGORY_LOOKUP, ToolSpec, localized_texts

NAME = "convert_currency"


def build_spec(bindings: ToolBindings) -> ToolSpec:
    """Declare the tool; the bindings are ignored because it needs no workspace."""
    return ToolSpec(
        name=NAME,
        handler=convert_currency,
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
        category=CATEGORY_LOOKUP,
        description_i18n=localized_texts(zh_cn=ZH_CN, zh_tw=ZH_TW, fr=FR, de=DE, ru=RU),
    )
