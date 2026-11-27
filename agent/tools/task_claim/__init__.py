"""``task_claim``: take ownership of a task whose prerequisites are done.

The rules of the board live in :mod:`agent.tools.task_board`, where it is kept in
:mod:`agent.tools.task_store`; this package only declares the call the model makes.
"""

from agent.tools.task_claim.description import (
    TASK_CLAIM_DESCRIPTION,
    TASK_CLAIM_PARAMETERS,
    TASK_CLAIM_TOOL_NAME,
)
from agent.tools.task_claim.tool import make_task_claim

__all__ = [
    "TASK_CLAIM_DESCRIPTION",
    "TASK_CLAIM_PARAMETERS",
    "TASK_CLAIM_TOOL_NAME",
    "make_task_claim",
]
