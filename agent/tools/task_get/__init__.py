"""``task_get``: one task in full, including the description someone else wrote.

The rules of the board live in :mod:`agent.tools.task_board`, where it is kept in
:mod:`agent.tools.task_store`; this package only declares the call the model makes.
"""

from agent.tools.task_get.description import (
    TASK_GET_DESCRIPTION,
    TASK_GET_PARAMETERS,
    TASK_GET_TOOL_NAME,
)
from agent.tools.task_get.tool import make_task_get

__all__ = [
    "TASK_GET_DESCRIPTION",
    "TASK_GET_PARAMETERS",
    "TASK_GET_TOOL_NAME",
    "make_task_get",
]
