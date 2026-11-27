"""The task board as the app binds it: which board a run sees, and how it is read.

``agent.tools`` must not import ``commons``/``dao`` (ADR 0019) and this package is
allowed to read live state, so the store the six ``task_*`` tools edit is injected
here - the same shape as :mod:`agent.runtime.todos`.

**Which board.** A conversation bound to a workspace sees that workspace's board, and
so does every other conversation in the project: that is what makes the board the
unit of coordination across conversations. A conversation with no workspace keeps a
board of its own. The id says which of the two, with a prefix, because the two depend
on different tables (``workspaces`` / ``sessions``) and a bare uuid would not say
where the board came from.
"""

from __future__ import annotations

from typing import Any, Dict, List

from agent.tools.task_board import board_state
from agent.tools.task_store import TaskBoard
from commons import state

BOARD_WORKSPACE_PREFIX = "workspace:"
BOARD_SESSION_PREFIX = "session:"


def resolve_board_id(session_id: str | None) -> str:
    """The board a conversation works on; empty when there is no conversation."""
    if not session_id:
        return ""
    session = state.monitor_store.get_session(session_id)
    workspace_id = str((session or {}).get("workspace_id") or "").strip()
    if workspace_id:
        return f"{BOARD_WORKSPACE_PREFIX}{workspace_id}"
    return f"{BOARD_SESSION_PREFIX}{session_id}"


class MonitorBoardStore:
    """``BoardStore`` over this process's task store (``dao/board_tasks.py``)."""

    def list_tasks(self, board_id: str) -> List[Dict[str, Any]]:
        return state.monitor_store.list_board_tasks(board_id)

    def get_task(self, board_id: str, task_id: str) -> Dict[str, Any] | None:
        return state.monitor_store.get_board_task(board_id, task_id)

    def create_task(
        self, board_id: str, subject: str, description: str
    ) -> Dict[str, Any]:
        return state.monitor_store.create_board_task(board_id, subject, description)

    def update_task(
        self, board_id: str, task_id: str, changes: Dict[str, Any]
    ) -> Dict[str, Any] | None:
        # The database method names its columns explicitly (so "leave the owner alone"
        # and "clear the owner" cannot be confused); the protocol passes a dict.
        return state.monitor_store.update_board_task(board_id, task_id, **changes)


def board_for_run(session_id: str | None, task_id: str = "") -> TaskBoard:
    """The board one run edits: the conversation's workspace, and who claims for it."""
    return TaskBoard(
        MonitorBoardStore(),
        resolve_board_id(session_id),
        session_id or "",
    )


def board_view(session_id: str | None) -> List[Dict[str, Any]]:
    """The board as the API returns it: derived state plus owners resolved to names.

    ``owner`` is a session id - useful to the tools, meaningless in a panel - so each
    one is looked up once per call and handed out as ``owner_name`` alongside it.
    """
    tasks = state.monitor_store.list_board_tasks(resolve_board_id(session_id))
    view = board_state(tasks)
    names: Dict[str, str] = {}
    for item in view:
        owner = item.get("owner")
        if not owner:
            item["owner_name"] = ""
            continue
        if owner not in names:
            session = state.monitor_store.get_session(owner) or {}
            names[owner] = str(session.get("name") or "")
        item["owner_name"] = names[owner]
    return view
