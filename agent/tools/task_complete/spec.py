"""The ``task_complete`` spec: a board edit, so nothing about the machine is asked."""

from agent.tools.bindings import ToolBindings
from agent.tools.permissions import PERMISSION_NONE
from agent.tools.spec import CATEGORY_OTHER, ToolSpec
from agent.tools.task_board_i18n import COMPLETE_TEXTS
from agent.tools.task_complete import (
    TASK_COMPLETE_DESCRIPTION,
    TASK_COMPLETE_PARAMETERS,
    TASK_COMPLETE_TOOL_NAME,
    make_task_complete,
)

NAME = TASK_COMPLETE_TOOL_NAME


def build_spec(bindings: ToolBindings) -> ToolSpec:
    """Bind the board tool to this run's board (its workspace, and its conversation)."""
    return ToolSpec(
        name=NAME,
        handler=make_task_complete(bindings.task_board),
        description=TASK_COMPLETE_DESCRIPTION,
        parameters=TASK_COMPLETE_PARAMETERS,
        permission=PERMISSION_NONE,
        category=CATEGORY_OTHER,
        description_i18n=COMPLETE_TEXTS,
    )
