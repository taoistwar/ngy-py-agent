"""The ``task_get`` call: one task in full, for resuming someone else's work."""

from __future__ import annotations

from typing import Any, Optional

from agent.models import ToolOutcome
from agent.tools.task_board import TaskBoardError, render_task, run_board_action, success
from agent.tools.task_store import TaskBoard


def make_task_get(board: Optional[TaskBoard] = None):
    """Bind the call to one board (``None`` keeps it in memory for this run)."""
    bound = board if board is not None else TaskBoard()

    def task_get(task_id: Any = None) -> ToolOutcome:
        def action() -> ToolOutcome:
            wanted = str(task_id or "").strip()
            task = bound.get(wanted) if wanted else None
            if task is None:
                raise TaskBoardError(f"no task {wanted} on this board", "not_found")
            return success(render_task(task, bound.owner), task=task)

        return run_board_action(action)

    return task_get
