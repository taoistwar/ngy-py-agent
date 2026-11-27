"""What the model is told about ``task_get``: name, description and schema."""

from __future__ import annotations

from typing import Any, Dict

TASK_GET_TOOL_NAME = "task_get"

TASK_GET_DESCRIPTION = (
    "Read one task from this project's task board in full: its description, "
    "prerequisites and owner. 'task_list' is the one-line overview; this is what a "
    "conversation reads before continuing someone else's task, because the acceptance "
    "criteria and the files involved live in the description, not in the subject."
)

TASK_GET_PARAMETERS: Dict[str, Any] = {
    "type": "object",
    "properties": {
        "task_id": {
            "type": "string",
            "description": "The task to read, exactly as the board lists it.",
        }
    },
    "required": ["task_id"],
}
