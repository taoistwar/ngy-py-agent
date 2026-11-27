"""What the model is told about ``task_complete``: name, description and schema."""

from __future__ import annotations

from typing import Any, Dict

TASK_COMPLETE_TOOL_NAME = "task_complete"

TASK_COMPLETE_DESCRIPTION = (
    "Mark the task this conversation claimed as completed, and report which tasks that "
    "unblocked. Only an 'in_progress' task owned by this conversation can be completed: "
    "a task claimed somewhere else has to be finished there, so the error names its "
    "owner instead of overriding it. Complete as soon as the work is verified rather "
    "than at the end of the session - the next task in the graph is waiting on this "
    "one, and finishing it is what lets that one start."
)

TASK_COMPLETE_PARAMETERS: Dict[str, Any] = {
    "type": "object",
    "properties": {
        "task_id": {
            "type": "string",
            "description": "The task to complete, exactly as the board lists it.",
        }
    },
    "required": ["task_id"],
}
