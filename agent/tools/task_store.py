"""Where a board's tasks live, and the run-scoped view the task tools edit.

A board outlives the run that created it: it belongs to a **workspace** (shared by
every conversation in that project) or, for a conversation with no workspace, to that
conversation. The binding object carries that id plus who a claim is recorded as, so
the six ``task_*`` tools never have to know which of the two they are looking at.

Persistence is a contract rather than an implementation because ``agent.tools`` must
not import ``commons``/``dao`` (ADR 0019): the app layer injects a store
(``agent.runtime.board`` binds the database one) and a run with no store keeps the
board in memory, which is what tests and library callers get.
"""

from __future__ import annotations

import secrets
from datetime import UTC, datetime
from typing import Any, Dict, List, Optional, Protocol

from agent.tools.task_board import (
    DEFAULT_OWNER,
    STATUS_PENDING,
)


class BoardStore(Protocol):
    """The five things a board needs: list, read one, create, update, (drop)."""

    def list_tasks(self, board_id: str) -> List[Dict[str, Any]]:
        """Every task on the board, oldest first."""

    def get_task(self, board_id: str, task_id: str) -> Optional[Dict[str, Any]]:
        """One task, or ``None`` when it is not on this board."""

    def create_task(
        self, board_id: str, subject: str, description: str
    ) -> Dict[str, Any]:
        """Insert a pending, unowned task and return it with its generated id."""

    def update_task(
        self, board_id: str, task_id: str, changes: Dict[str, Any]
    ) -> Optional[Dict[str, Any]]:
        """Write ``changes`` (status / owner / blocked_by); ``None`` when absent."""


class MemoryBoardStore:
    """A store with no persistence: one process, one dictionary.

    The fallback for a run nobody bound a database to. The board still works inside
    the process (a test can create, claim and complete), it just does not outlive it.
    """

    def __init__(self) -> None:
        self._boards: Dict[str, Dict[str, Dict[str, Any]]] = {}

    def list_tasks(self, board_id: str) -> List[Dict[str, Any]]:
        board = self._boards.get(board_id or "", {})
        return [dict(task) for task in board.values()]

    def get_task(self, board_id: str, task_id: str) -> Optional[Dict[str, Any]]:
        task = self._boards.get(board_id or "", {}).get(task_id)
        return dict(task) if task is not None else None

    def create_task(self, board_id: str, subject: str, description: str) -> Dict[str, Any]:
        board = self._boards.setdefault(board_id or "", {})
        task_id = f"task_{secrets.token_hex(4)}"
        while task_id in board:
            task_id = f"task_{secrets.token_hex(4)}"
        now = datetime.now(UTC)
        task = {
            "board_id": board_id or "",
            "task_id": task_id,
            "subject": subject,
            "description": description,
            "status": STATUS_PENDING,
            "owner": None,
            "blocked_by": [],
            "created_at": now,
            "updated_at": now,
        }
        board[task_id] = task
        return dict(task)

    def update_task(
        self, board_id: str, task_id: str, changes: Dict[str, Any]
    ) -> Optional[Dict[str, Any]]:
        task = self._boards.get(board_id or "", {}).get(task_id)
        if task is None:
            return None
        task.update(changes)
        task["updated_at"] = datetime.now(UTC)
        return dict(task)


class TaskBoard:
    """One board as this run sees it: which board, and who a claim belongs to.

    ``owner`` is the conversation this run belongs to, not the tool layer's idea: only
    the app layer knows it, and a claim recorded as a random run id could never be
    completed by the run's own follow-up task.
    """

    def __init__(
        self,
        store: Optional[BoardStore] = None,
        board_id: str = "",
        owner: str = "",
    ) -> None:
        self.store: BoardStore = store if store is not None else MemoryBoardStore()
        self.board_id = board_id or ""
        self.owner = owner or ""

    @property
    def claimant(self) -> str:
        """The owner string a claim is written with."""
        return self.owner or DEFAULT_OWNER

    def list(self) -> List[Dict[str, Any]]:
        return [dict(task) for task in self.store.list_tasks(self.board_id)]

    def get(self, task_id: str) -> Optional[Dict[str, Any]]:
        return self.store.get_task(self.board_id, task_id)

    def create(self, subject: str, description: str = "") -> Dict[str, Any]:
        return self.store.create_task(self.board_id, subject, description)

    def update(self, task_id: str, **changes: Any) -> Optional[Dict[str, Any]]:
        return self.store.update_task(self.board_id, task_id, changes)
