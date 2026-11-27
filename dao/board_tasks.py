"""The task board: units of work a project still has to do, and what blocks them.

Not to be confused with ``tasks`` in the same database. A *task* there is one agent
run; a **board task** is a piece of the project's work that outlives a conversation:
created once, claimed by the conversation doing it, and unblocked when everything it
waits for is done (ADR 0033).

One row per work item, keyed by the board it belongs to. A workspace shares one board
across its conversations; a conversation with no workspace keeps its own. The rows
carry no derived state (a task is not "ready", it is "pending with satisfied
prerequisites") - that is computed in ``agent/tools/task_board.py``, so the two cannot
disagree about what is blocked.
"""

from __future__ import annotations

import json
import secrets
import sqlite3
from datetime import UTC, datetime
from typing import Any

# What the tool layer validates before writing; the column is plain text, so this is
# the list the API and the tools agree on rather than a database constraint.
STATUSES = ("pending", "in_progress", "completed")

# "Leave this column alone" for ``update_board_task``: ``None`` is a value (a task
# losing its owner), so it cannot double as "unchanged".
_UNSET: Any = object()


class _BoardTaskMixin:
    """Board task persistence: one board per workspace (or per unbound conversation)."""

    def _board_task_to_dict(self, row: sqlite3.Row) -> dict[str, Any]:
        try:
            blocked_by = json.loads(row["blocked_by"] or "[]")
        except ValueError:
            # A row this module did not write: show no dependencies rather than
            # making every reader of the board fail.
            blocked_by = []
        return {
            "board_id": row["board_id"],
            "task_id": row["task_id"],
            "subject": row["subject"],
            "description": row["description"],
            "status": row["status"],
            "owner": row["owner"],
            "blocked_by": blocked_by if isinstance(blocked_by, list) else [],
            "created_at": self._parse_datetime(row["created_at"]),
            "updated_at": self._parse_datetime(row["updated_at"]),
        }

    def list_board_tasks(self, board_id: str | None) -> list[dict[str, Any]]:
        """Every task on one board, oldest first (the order it is shown in).

        Ordered by ``rowid`` rather than ``created_at``: the wall clock on this host
        can hand the same timestamp to two inserts a millisecond apart, and a board
        whose rows shuffle between two polls is worse than one sorted by an implicit
        sequence nobody sees.
        """
        if not board_id:
            return []
        with self._lock:
            rows = self._conn.execute(
                """
                SELECT board_id, task_id, subject, description, status, owner,
                       blocked_by, created_at, updated_at
                FROM board_tasks
                WHERE board_id = ?
                ORDER BY rowid ASC
                """,
                (board_id,),
            ).fetchall()
        return [self._board_task_to_dict(row) for row in rows]

    def get_board_task(self, board_id: str | None, task_id: str) -> dict[str, Any] | None:
        if not board_id:
            return None
        with self._lock:
            row = self._conn.execute(
                """
                SELECT board_id, task_id, subject, description, status, owner,
                       blocked_by, created_at, updated_at
                FROM board_tasks
                WHERE board_id = ? AND task_id = ?
                """,
                (board_id, task_id),
            ).fetchone()
        return self._board_task_to_dict(row) if row is not None else None

    def create_board_task(
        self,
        board_id: str,
        subject: str,
        description: str = "",
    ) -> dict[str, Any]:
        """Insert a pending, unowned task and return it with its generated id."""
        now = datetime.now(UTC).isoformat()
        with self._lock:
            # The lock makes "is this id taken?" and the insert one step, so the id
            # is unique without relying on an exception to tell us it was not.
            for _ in range(100):
                task_id = f"task_{secrets.token_hex(4)}"
                taken = self._conn.execute(
                    "SELECT 1 FROM board_tasks WHERE board_id = ? AND task_id = ?",
                    (board_id, task_id),
                ).fetchone()
                if taken is not None:
                    continue
                self._conn.execute(
                    """
                    INSERT INTO board_tasks (
                        board_id, task_id, subject, description, status, owner,
                        blocked_by, created_at, updated_at
                    ) VALUES (?, ?, ?, ?, ?, NULL, ?, ?, ?)
                    """,
                    (board_id, task_id, subject, description, "pending", "[]", now, now),
                )
                self._conn.commit()
                return {
                    "board_id": board_id,
                    "task_id": task_id,
                    "subject": subject,
                    "description": description,
                    "status": "pending",
                    "owner": None,
                    "blocked_by": [],
                    "created_at": self._parse_datetime(now),
                    "updated_at": self._parse_datetime(now),
                }
        raise RuntimeError("could not allocate a unique board task id")

    def update_board_task(
        self,
        board_id: str,
        task_id: str,
        *,
        status: str | None = None,
        owner: Any = _UNSET,
        blocked_by: list[str] | None = None,
    ) -> dict[str, Any] | None:
        """Write the given columns; ``None`` when the task is not on this board."""
        assignments = ["updated_at = ?"]
        values: list[Any] = [datetime.now(UTC).isoformat()]
        if status is not None:
            assignments.append("status = ?")
            values.append(status)
        if owner is not _UNSET:
            assignments.append("owner = ?")
            values.append(owner)
        if blocked_by is not None:
            assignments.append("blocked_by = ?")
            values.append(json.dumps(list(blocked_by), ensure_ascii=False))
        values.extend([board_id, task_id])

        with self._lock:
            cursor = self._conn.execute(
                f"UPDATE board_tasks SET {', '.join(assignments)} "
                "WHERE board_id = ? AND task_id = ?",
                values,
            )
            self._conn.commit()
            updated = int(cursor.rowcount or 0) > 0
        # Read back outside the lock: ``get_board_task`` takes it again.
        return self.get_board_task(board_id, task_id) if updated else None

    def delete_board_tasks(self, board_id: str) -> int:
        with self._lock:
            cursor = self._conn.execute(
                "DELETE FROM board_tasks WHERE board_id = ?", (board_id,)
            )
            self._conn.commit()
            return int(cursor.rowcount or 0)
