"""The ``task_get`` spec: reads the board, changes nothing."""

from agent.tools.bindings import ToolBindings
from agent.tools.permissions import PERMISSION_NONE
from agent.tools.spec import CATEGORY_OTHER, ToolSpec
from agent.tools.task_board_i18n import GET_TEXTS
from agent.tools.task_get import (
    TASK_GET_DESCRIPTION,
    TASK_GET_PARAMETERS,
    TASK_GET_TOOL_NAME,
    make_task_get,
)

NAME = TASK_GET_TOOL_NAME


def build_spec(bindings: ToolBindings) -> ToolSpec:
    """Bind the board tool to this run's board (its workspace, and its conversation)."""
    return ToolSpec(
        name=NAME,
        handler=make_task_get(bindings.task_board),
        description=TASK_GET_DESCRIPTION,
        parameters=TASK_GET_PARAMETERS,
        permission=PERMISSION_NONE,
        category=CATEGORY_OTHER,
        description_i18n=GET_TEXTS,
    )
