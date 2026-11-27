"""The ``task_create`` spec: a board edit, so nothing about the machine is asked."""

from agent.tools.bindings import ToolBindings
from agent.tools.permissions import PERMISSION_NONE
from agent.tools.spec import CATEGORY_TASK, ToolSpec
from agent.tools.task_board_i18n import CREATE_TEXTS
from agent.tools.task_create import (
    TASK_CREATE_DESCRIPTION,
    TASK_CREATE_PARAMETERS,
    TASK_CREATE_TOOL_NAME,
    make_task_create,
)

NAME = TASK_CREATE_TOOL_NAME


def build_spec(bindings: ToolBindings) -> ToolSpec:
    """Bind the board tool to this run's board (its workspace, and its conversation)."""
    return ToolSpec(
        name=NAME,
        handler=make_task_create(bindings.task_board),
        description=TASK_CREATE_DESCRIPTION,
        parameters=TASK_CREATE_PARAMETERS,
        # A board row is a note in this app's own database: no file, no network, and
        # nothing a confirmation dialog could protect.
        permission=PERMISSION_NONE,
        category=CATEGORY_TASK,
        description_i18n=CREATE_TEXTS,
    )
