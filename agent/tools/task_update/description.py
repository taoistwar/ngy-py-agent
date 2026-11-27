"""What the model is told about ``task_update``: name, description and schema."""

from __future__ import annotations

from typing import Any, Dict

TASK_UPDATE_TOOL_NAME = "task_update"

TASK_UPDATE_DESCRIPTION = (
    "Add prerequisites to a task on this project's task board. This is how the board is "
    "sequenced: create every task first, then call this once per edge with the ids "
    "'task_create' returned. A task can be claimed only when every id in its "
    "'blocked_by' is completed, so an edge is what says 'not before that one'. Only a "
    "pending, unclaimed task can be changed - rewriting the prerequisites of work "
    "someone already started would change what 'done' means for them. Self-"
    "dependencies, cycles and unknown ids are refused; adding an edge that is already "
    "there is a no-op, so this call is safe to repeat."
)

TASK_UPDATE_PARAMETERS: Dict[str, Any] = {
    "type": "object",
    "properties": {
        "task_id": {
            "type": "string",
            "description": "The task to change, exactly as task_create returned it.",
        },
        "add_blocked_by": {
            "type": "array",
            "items": {"type": "string"},
            "minItems": 1,
            "description": (
                "Ids of the tasks that must be completed before this one can start. "
                "Added to the existing list, never replacing it."
            ),
        },
    },
    "required": ["task_id", "add_blocked_by"],
}
