"""The ``code_interpreter`` spec: name, schema and permission kind."""

from agent.tools.bindings import ToolBindings
from agent.tools.code_interpreter.tool import code_interpreter
from agent.tools.permissions import PERMISSION_EXEC
from agent.tools.spec import ToolSpec

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
    )
