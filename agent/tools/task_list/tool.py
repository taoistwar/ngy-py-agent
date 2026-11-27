"""The ``task_list`` call: the whole board, one line per task."""

from __future__ import annotations

from typing import Optional

from agent.models import ToolOutcome
from agent.tools.task_board import board_state, counts, render_list, run_board_action, success
from agent.tools.task_store import TaskBoard


def make_task_list(board: Optional[TaskBoard] = None):
    """Bind the call to one board (``None`` keeps it in memory for this run)."""
    bound = board if board is not None else TaskBoard()

    def task_list() -> ToolOutcome:
        def action() -> ToolOutcome:
            tasks = bound.list()
            return success(
                render_list(tasks, bound.owner),
                tasks=board_state(tasks),
                counts=counts(tasks),
            )

        return run_board_action(action)

    return task_list
