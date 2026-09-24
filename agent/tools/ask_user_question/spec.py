"""The ``ask_user_question`` spec: name, description, schema, binding.

``permission`` stays ``none``: asking a question is not a privileged action, and a
confirmation dialog in front of it would be the exact confusion the tool's own
description forbids. Nothing here can touch the machine, so there is no kind to declare
(ADR 0010 D6).
"""

from agent.tools.ask_user_question import (
    ASK_USER_QUESTION_DESCRIPTION,
    ASK_USER_QUESTION_PARAMETERS,
    ASK_USER_QUESTION_TOOL_NAME,
    make_ask_user_question_tool,
)
from agent.tools.bindings import ToolBindings
from agent.tools.permissions import PERMISSION_NONE
from agent.tools.spec import ToolSpec

NAME = ASK_USER_QUESTION_TOOL_NAME


def build_spec(bindings: ToolBindings) -> ToolSpec:
    """Bind the question tool to this run's channel."""
    return ToolSpec(
        name=NAME,
        handler=make_ask_user_question_tool(bindings.ask_user),
        description=ASK_USER_QUESTION_DESCRIPTION,
        parameters=ASK_USER_QUESTION_PARAMETERS,
        permission=PERMISSION_NONE,
    )
