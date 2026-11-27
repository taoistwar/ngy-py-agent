"""The ``task_create`` call: insert one node and hand back its id."""

from __future__ import annotations

from typing import Any, Optional

from agent.models import ToolOutcome
from agent.tools.task_board import (
    run_board_action,
    success,
    validate_description,
    validate_subject,
)
from agent.tools.task_store import TaskBoard


def make_task_create(board: Optional[TaskBoard] = None):
    """Bind the call to one board (``None`` keeps it in memory for this run)."""
    bound = board if board is not None else TaskBoard()

    def task_create(subject: Any = None, description: Any = "") -> ToolOutcome:
        def action() -> ToolOutcome:
            task = bound.create(
                validate_subject(subject), validate_description(description)
            )
            return success(
                f"Created {task['task_id']}: {task['subject']}\n"
                "Add its prerequisites with task_update using ids returned by "
                "task_create, then claim it with task_claim when it can start.",
                task=task,
            )

        return run_board_action(action)

    return task_create
