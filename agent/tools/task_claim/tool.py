"""The ``task_claim`` call: pending -> in_progress, owned by this conversation."""

from __future__ import annotations

from typing import Any, Optional

from agent.models import ToolOutcome
from agent.tools.task_board import TaskBoardError, plan_claim, run_board_action, success
from agent.tools.task_store import TaskBoard


def make_task_claim(board: Optional[TaskBoard] = None):
    """Bind the call to one board (``None`` keeps it in memory for this run)."""
    bound = board if board is not None else TaskBoard()

    def task_claim(task_id: Any = None) -> ToolOutcome:
        def action() -> ToolOutcome:
            wanted = str(task_id or "").strip()
            # The owner is the conversation, injected by the app layer - never a tool
            # argument: a model that could name its own owner could claim a task it
            # does not own and finish someone else's work.
            changes = plan_claim(bound.list(), wanted, bound.claimant)
            updated = bound.update(wanted, **changes)
            if updated is None:
                raise TaskBoardError(f"no task {wanted} on this board", "not_found")
            return success(
                f"Claimed {updated['task_id']} ({updated['subject']})",
                task=updated,
            )

        return run_board_action(action)

    return task_claim
