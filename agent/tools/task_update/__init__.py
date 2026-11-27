"""``task_update``: add prerequisites to a task on the project's board.

The rules of the board live in :mod:`agent.tools.task_board`, where it is kept in
:mod:`agent.tools.task_store`; this package only declares the call the model makes.
"""

from agent.tools.task_update.description import (
    TASK_UPDATE_DESCRIPTION,
    TASK_UPDATE_PARAMETERS,
    TASK_UPDATE_TOOL_NAME,
)
from agent.tools.task_update.tool import make_task_update

__all__ = [
    "TASK_UPDATE_DESCRIPTION",
    "TASK_UPDATE_PARAMETERS",
    "TASK_UPDATE_TOOL_NAME",
    "make_task_update",
]
