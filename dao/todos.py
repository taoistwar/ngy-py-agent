"""The plan a session's ``todo_write`` tool maintains.

The list belongs to the **session**, not to the task that wrote it: a follow-up task
in the same conversation continues the same checklist, and the web admin reads it
through the task detail response, which resolves it via the task's session. One row
per session, replaced whole on every call - a plan is a snapshot, not a log.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Any


class _TodoMixin:
    """Session-scoped plan persistence."""

    def get_session_todos(self, session_id: str | None) -> dict[str, Any] | None:
        """The session's plan (items plus who wrote it last), or ``None``."""
        if not session_id:
            return None
        with self._lock:
            row = self._conn.execute(
                "SELECT session_id, items, task_id, updated_at FROM session_todos "
                "WHERE session_id = ?",
                (session_id,),
            ).fetchone()
        if row is None:
            return None
        try:
            items = json.loads(row["items"] or "[]")
        except ValueError:
            # A row this module did not write: report "no plan" rather than crashing
            # the task detail endpoint every second.
            items = []
        return {
            "session_id": row["session_id"],
            "task_id": row["task_id"] or "",
            "updated_at": self._parse_datetime(row["updated_at"]),
            "todos": items if isinstance(items, list) else [],
        }

    def set_session_todos(
        self,
        session_id: str,
        todos: list[dict[str, Any]],
        task_id: str = "",
    ) -> None:
        """Replace the session's plan; the writing task and the time are recorded."""
        if not session_id:
            # Without a session there is nowhere to keep it: a task always has one,
            # so this is a caller bug rather than a state to store.
            return
        now = datetime.now(UTC).isoformat()
        with self._lock:
            self._conn.execute(
                """
                INSERT OR REPLACE INTO session_todos (session_id, items, task_id, updated_at)
                VALUES (?, ?, ?, ?)
                """,
                (session_id, json.dumps(list(todos), ensure_ascii=False), task_id or "", now),
            )
            self._conn.commit()

    def clear_session_todos(self, session_id: str) -> bool:
        with self._lock:
            cursor = self._conn.execute(
                "DELETE FROM session_todos WHERE session_id = ?", (session_id,)
            )
            self._conn.commit()
            return (cursor.rowcount or 0) > 0
