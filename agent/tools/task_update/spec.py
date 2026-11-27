"""The ``task_update`` spec: a board edit, so nothing about the machine is asked."""

from agent.tools.bindings import ToolBindings
from agent.tools.permissions import PERMISSION_NONE
from agent.tools.spec import CATEGORY_TASK, ToolSpec
from agent.tools.task_board_i18n import UPDATE_TEXTS
from agent.tools.task_update import (
    TASK_UPDATE_DESCRIPTION,
    TASK_UPDATE_PARAMETERS,
    TASK_UPDATE_TOOL_NAME,
    make_task_update,
)

NAME = TASK_UPDATE_TOOL_NAME


def build_spec(bindings: ToolBindings) -> ToolSpec:
    """Bind the board tool to this run's board (its workspace, and its conversation)."""
    return ToolSpec(
        name=NAME,
        handler=make_task_update(bindings.task_board),
        description=TASK_UPDATE_DESCRIPTION,
        parameters=TASK_UPDATE_PARAMETERS,
        permission=PERMISSION_NONE,
        category=CATEGORY_TASK,
        description_i18n=UPDATE_TEXTS,
    )
