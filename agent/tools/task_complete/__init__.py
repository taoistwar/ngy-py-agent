"""``task_complete``: finish a claimed task and report what it unblocked.

The rules of the board live in :mod:`agent.tools.task_board`, where it is kept in
:mod:`agent.tools.task_store`; this package only declares the call the model makes.
"""

from agent.tools.task_complete.description import (
    TASK_COMPLETE_DESCRIPTION,
    TASK_COMPLETE_PARAMETERS,
    TASK_COMPLETE_TOOL_NAME,
)
from agent.tools.task_complete.tool import make_task_complete

__all__ = [
    "TASK_COMPLETE_DESCRIPTION",
    "TASK_COMPLETE_PARAMETERS",
    "TASK_COMPLETE_TOOL_NAME",
    "make_task_complete",
]
