"""The ``todo_write`` spec: name, description, schema, session binding.

``permission`` stays ``none``: a plan is a note to itself. Nothing here touches the
machine or reaches the network, and a confirmation dialog in front of "list the
steps" would be a question with no stakes.
"""

from agent.tools.bindings import ToolBindings
from agent.tools.permissions import PERMISSION_NONE
from agent.tools.spec import CATEGORY_TASK, ToolSpec, localized_texts
from agent.tools.todo_write import (
    TODO_WRITE_DESCRIPTION,
    TODO_WRITE_PARAMETERS,
    TODO_WRITE_TOOL_NAME,
    make_todo_write_tool,
)
from agent.tools.todo_write.i18n import DE, FR, RU, ZH_CN, ZH_TW

NAME = TODO_WRITE_TOOL_NAME


def build_spec(bindings: ToolBindings) -> ToolSpec:
    """Bind the plan tool to this run's session board."""
    return ToolSpec(
        name=NAME,
        handler=make_todo_write_tool(bindings.todo_board),
        description=TODO_WRITE_DESCRIPTION,
        parameters=TODO_WRITE_PARAMETERS,
        permission=PERMISSION_NONE,
        category=CATEGORY_TASK,
        description_i18n=localized_texts(zh_cn=ZH_CN, zh_tw=ZH_TW, fr=FR, de=DE, ru=RU),
    )
