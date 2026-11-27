"""What the model is told about ``task_claim``: name, description and schema."""

from __future__ import annotations

from typing import Any, Dict

TASK_CLAIM_TOOL_NAME = "task_claim"

TASK_CLAIM_DESCRIPTION = (
    "Claim a task on this project's task board: it becomes 'in_progress' and is "
    "recorded as owned by this conversation. Only a pending task whose prerequisites "
    "are all completed can be claimed; a blocked one answers with what it is waiting "
    "for, which is the board telling you to do that task first. Claim before starting "
    "the work so another conversation does not start the same task, and complete it "
    "with 'task_complete' when it is done - the tasks that wait for it cannot start "
    "until then."
)

TASK_CLAIM_PARAMETERS: Dict[str, Any] = {
    "type": "object",
    "properties": {
        "task_id": {
            "type": "string",
            "description": "The task to claim, exactly as the board lists it.",
        }
    },
    "required": ["task_id"],
}
