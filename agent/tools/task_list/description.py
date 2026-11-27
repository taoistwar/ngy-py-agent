"""What the model is told about ``task_list``: name, description and schema."""

from __future__ import annotations

from typing import Any, Dict

TASK_LIST_TOOL_NAME = "task_list"

TASK_LIST_DESCRIPTION = (
    "List this project's task board: one line per task with its id, subject, status, "
    "owner and whether it can be claimed now. Read it first when you start on a "
    "project that may already have a plan - an earlier conversation could have created "
    "tasks and left some of them finished - and again after completing one, to see "
    "which tasks it unblocked. The board is shared by the workspace, so the list is not "
    "only yours."
)

TASK_LIST_PARAMETERS: Dict[str, Any] = {"type": "object", "properties": {}}
