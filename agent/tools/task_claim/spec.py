"""The ``task_claim`` spec: a board edit, so nothing about the machine is asked."""

from agent.tools.bindings import ToolBindings
from agent.tools.permissions import PERMISSION_NONE
from agent.tools.spec import CATEGORY_TASK, ToolSpec
from agent.tools.task_board_i18n import CLAIM_TEXTS
from agent.tools.task_claim import (
    TASK_CLAIM_DESCRIPTION,
    TASK_CLAIM_PARAMETERS,
    TASK_CLAIM_TOOL_NAME,
    make_task_claim,
)

NAME = TASK_CLAIM_TOOL_NAME


def build_spec(bindings: ToolBindings) -> ToolSpec:
    """Bind the board tool to this run's board (its workspace, and its conversation)."""
    return ToolSpec(
        name=NAME,
        handler=make_task_claim(bindings.task_board),
        description=TASK_CLAIM_DESCRIPTION,
        parameters=TASK_CLAIM_PARAMETERS,
        permission=PERMISSION_NONE,
        category=CATEGORY_TASK,
        description_i18n=CLAIM_TEXTS,
    )
