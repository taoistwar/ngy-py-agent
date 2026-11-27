"""The ``task_complete`` call: in_progress -> completed, and what that unblocks."""

from __future__ import annotations

from typing import Any, Optional

from agent.models import ToolOutcome
from agent.tools.task_board import (
    TaskBoardError,
    plan_complete,
    run_board_action,
    success,
)
from agent.tools.task_store import TaskBoard


def make_task_complete(board: Optional[TaskBoard] = None):
    """Bind the call to one board (``None`` keeps it in memory for this run)."""
    bound = board if board is not None else TaskBoard()

    def task_complete(task_id: Any = None) -> ToolOutcome:
        def action() -> ToolOutcome:
            wanted = str(task_id or "").strip()
            changes, unblocked = plan_complete(bound.list(), wanted, bound.claimant)
            updated = bound.update(wanted, **changes)
            if updated is None:
                raise TaskBoardError(f"no task {wanted} on this board", "not_found")

            # "Unblocked" is the answer to "what can happen next": without it the
            # model would have to list the board again to find out.
            text = f"Completed {updated['task_id']} ({updated['subject']})"
            if unblocked:
                text += "\nUnblocked: " + ", ".join(
                    f"{task['task_id']} ({task['subject']})" for task in unblocked
                )
            return success(
                text,
                task=updated,
                unblocked=[task["task_id"] for task in unblocked],
            )

        return run_board_action(action)

    return task_complete
