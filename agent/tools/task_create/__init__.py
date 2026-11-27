"""``task_create``: add one node to the project's task board.

The rules of the board live in :mod:`agent.tools.task_board`, where it is kept in
:mod:`agent.tools.task_store`; this package only declares the call the model makes.
"""

from agent.tools.task_create.description import (
    TASK_CREATE_DESCRIPTION,
    TASK_CREATE_PARAMETERS,
    TASK_CREATE_TOOL_NAME,
)
from agent.tools.task_create.tool import make_task_create

__all__ = [
    "TASK_CREATE_DESCRIPTION",
    "TASK_CREATE_PARAMETERS",
    "TASK_CREATE_TOOL_NAME",
    "make_task_create",
]
