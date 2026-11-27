"""The ``task_update`` call: validate one edge (or a batch) and store it."""

from __future__ import annotations

from typing import Any, Optional

from agent.models import ToolOutcome
from agent.tools.task_board import (
    TaskBoardError,
    incomplete_blockers,
    index_by_id,
    is_ready,
    merged_dependencies,
    run_board_action,
    success,
)
from agent.tools.task_store import TaskBoard


def make_task_update(board: Optional[TaskBoard] = None):
    """Bind the call to one board (``None`` keeps it in memory for this run)."""
    bound = board if board is not None else TaskBoard()

    def task_update(task_id: Any = None, add_blocked_by: Any = None) -> ToolOutcome:
        def action() -> ToolOutcome:
            wanted = str(task_id or "").strip()
            blocked_by = merged_dependencies(bound.list(), wanted, add_blocked_by)
            updated = bound.update(wanted, blocked_by=blocked_by)
            if updated is None:
                raise TaskBoardError(f"no task {wanted} on this board", "not_found")

            # Say what the edge did, not only that it was stored: "still blocked by"
            # is the fact the model needs before it tries to claim the task.
            index = index_by_id(bound.list())
            waiting = incomplete_blockers(updated, index)
            if is_ready(updated, index):
                note = "\nIt can be claimed now."
            elif waiting:
                note = f"\nStill blocked by {', '.join(waiting)}."
            else:
                note = ""

            return success(
                f"Updated {updated['task_id']} blocked by: "
                f"{', '.join(updated.get('blocked_by') or []) or 'none'}{note}",
                task=updated,
            )

        return run_board_action(action)

    return task_update
