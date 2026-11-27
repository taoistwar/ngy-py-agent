"""What the model is told about ``task_create``: name, description and schema."""

from __future__ import annotations

from typing import Any, Dict

TASK_CREATE_TOOL_NAME = "task_create"

# The last paragraph is the part that matters: the board and ``todo_write`` both look
# like "a list of things to do", and only one of them survives the conversation.
TASK_CREATE_DESCRIPTION = (
    "Create one task on this project's task board: a unit of work with an id, an owner "
    "and prerequisites. The board is the project's plan, not this conversation's "
    "checklist - use 'todo_write' for the steps you are doing right now, and this tool "
    "for work that has to outlive the conversation or that a later conversation has to "
    "pick up. Write every task first and read the generated ids from the results, then "
    "add the prerequisites with 'task_update': a call cannot use an id that another "
    "call in the same turn has not returned yet. The subject is one short imperative "
    "line; the description is where 'done' is defined - files, acceptance checks, "
    "anything the next conversation needs to continue. Tasks start 'pending' and "
    "unowned; 'task_claim' is what starts one."
)

TASK_CREATE_PARAMETERS: Dict[str, Any] = {
    "type": "object",
    "properties": {
        "subject": {
            "type": "string",
            "description": "One short imperative line: what the task delivers.",
        },
        "description": {
            "type": "string",
            "description": (
                "What done means: acceptance checks, files involved, constraints. Left "
                "empty when the subject says it all."
            ),
        },
    },
    "required": ["subject"],
}
