"""The ``task_list`` spec: reads the board, changes nothing."""

from agent.tools.bindings import ToolBindings
from agent.tools.permissions import PERMISSION_NONE
from agent.tools.spec import CATEGORY_OTHER, ToolSpec
from agent.tools.task_board_i18n import LIST_TEXTS
from agent.tools.task_list import (
    TASK_LIST_DESCRIPTION,
    TASK_LIST_PARAMETERS,
    TASK_LIST_TOOL_NAME,
    make_task_list,
)

NAME = TASK_LIST_TOOL_NAME


def build_spec(bindings: ToolBindings) -> ToolSpec:
    """Bind the board tool to this run's board (its workspace, and its conversation)."""
    return ToolSpec(
        name=NAME,
        handler=make_task_list(bindings.task_board),
        description=TASK_LIST_DESCRIPTION,
        parameters=TASK_LIST_PARAMETERS,
        permission=PERMISSION_NONE,
        category=CATEGORY_OTHER,
        description_i18n=LIST_TEXTS,
    )
