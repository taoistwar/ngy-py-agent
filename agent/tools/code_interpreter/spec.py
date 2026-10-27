"""The ``code_interpreter`` spec: name, schema and permission kind."""

from agent.tools.bindings import ToolBindings
from agent.tools.code_interpreter.i18n import DE, FR, RU, ZH_CN, ZH_TW
from agent.tools.code_interpreter.tool import code_interpreter
from agent.tools.permissions import PERMISSION_EXEC
from agent.tools.spec import CATEGORY_COMPUTE, ToolSpec, localized_texts

NAME = "code_interpreter"


def build_spec(bindings: ToolBindings) -> ToolSpec:
    """Declare the tool; the bindings are ignored because it needs no workspace."""
    return ToolSpec(
        name=NAME,
        handler=code_interpreter,
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
        # Arbitrary code: this is one of the two tools that can reach anything on the
        # machine, which is why it is confirmed (ADR 0006 D2).
        permission=PERMISSION_EXEC,
        category=CATEGORY_COMPUTE,
        description_i18n=localized_texts(zh_cn=ZH_CN, zh_tw=ZH_TW, fr=FR, de=DE, ru=RU),
    )
