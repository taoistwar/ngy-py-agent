"""The ``todo_write`` call: validate the plan, store it, echo it back.

The call only edits the plan; the tools that do the work are the ones that already
exist. What this tool adds is not execution, it is planning - which is why a
rejected call is a model mistake worth explaining, and an empty list is legal: it is
how a plan is cleared.
"""

from __future__ import annotations

from typing import Any, Dict, Optional, Tuple

from agent.models import ToolOutcome
from agent.tools.todo_store import TodoBoard
from agent.tools.todo_write.items import counts, parse_todos, render_todos


def todo_write_impl(todos_raw: Any, board: Optional[TodoBoard]) -> Tuple[str, Dict[str, Any]]:
    """Validate and store a plan; returns ``(model_text, details)``."""
    items, error = parse_todos(todos_raw)
    if error is not None:
        raise TodoWriteError(error)

    if board is not None:
        # The store is the record; failing to write is an error the model has to
        # see, because the UI it promised to update did not get the update.
        board.replace(items)

    summary = counts(items)
    return render_todos(items), {
        "success": True,
        "todos": items,
        "counts": summary,
    }


class TodoWriteError(ValueError):
    """A plan that cannot be stored as sent in; the message is the whole answer."""

    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.message = message


def make_todo_write_tool(board: Optional[TodoBoard] = None):
    """Bind the tool to one session's plan (``None`` keeps it in memory).

    The fallback is a real board, not a disabled tool: a caller that built the tool
    from bare ``ToolBindings`` still gets a planner, it just keeps the list for the
    life of this handler (library callers, tests).
    """
    board = board if board is not None else TodoBoard()

    def todo_write(todos: Any = None) -> ToolOutcome:
        try:
            model_text, details = todo_write_impl(todos, board)
        except TodoWriteError as exc:
            return ToolOutcome(
                model_text=f"Error: {exc.message}",
                details={"success": False, "reason": "invalid_argument", "error": exc.message},
            )
        except Exception as exc:  # noqa: BLE001 - a store failure must reach the model
            return ToolOutcome(
                model_text=f"Error: the plan could not be saved: {exc}",
                details={"success": False, "reason": "store_error", "error": str(exc)},
            )
        return ToolOutcome(model_text=model_text, details=details)

    return todo_write
