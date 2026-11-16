"""Tasks and their event logs: the turns a session is made of."""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import uuid4

from agent.models import TaskEvent, TaskStatus
from dao.base import _USER_SETTLED_STATUSES


class _TaskMixin:
    """Task rows, task queries and the events each turn produced."""

    def create_task(
        self,
        query: str,
        provider: str,
        session_id: str | None = None,
        model_id: str | None = None,
        mode: str = "build",
    ) -> str:
        task_id = str(uuid4())
        now = datetime.now(UTC).isoformat()
        target_session = session_id or self.ensure_default_session()
        with self._lock:
            self._conn.execute(
                """
                INSERT INTO tasks (
                    task_id, query, name, provider, status, created_at, updated_at, session_id,
                    model_id, mode, result
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    task_id,
                    query,
                    "",
                    provider,
                    TaskStatus.RUNNING,
                    now,
                    now,
                    target_session,
                    model_id,
                    mode,
                    "",
                ),
            )
            self._conn.execute(
                "UPDATE sessions SET updated_at = ? WHERE session_id = ?",
                (now, target_session),
            )
            self._conn.commit()
        return task_id

    def touch_session(self, session_id: str | None) -> None:
        if not session_id:
            return
        with self._lock:
            self._conn.execute(
                "UPDATE sessions SET updated_at = ? WHERE session_id = ?",
                (datetime.now(UTC).isoformat(), session_id),
            )
            self._conn.commit()

    def delete_task(self, task_id: str) -> bool:
        with self._lock:
            cursor = self._conn.execute("DELETE FROM tasks WHERE task_id = ?", (task_id,))
            self._conn.commit()
            return (cursor.rowcount or 0) > 0

    def purge_expired_tasks(self, retention_days: int) -> int:
        if retention_days <= 0:
            return 0
        cutoff = datetime.now(UTC) - timedelta(days=retention_days)
        with self._lock:
            cursor = self._conn.execute(
                "DELETE FROM tasks WHERE created_at < ?",
                (cutoff.isoformat(),),
            )
            self._conn.commit()
            return int(cursor.rowcount or 0)

    def set_provider(self, task_id: str, provider: str) -> None:
        with self._lock:
            self._conn.execute(
                "UPDATE tasks SET provider = ?, updated_at = ? WHERE task_id = ?",
                (provider, datetime.now(UTC).isoformat(), task_id),
            )
            self._conn.commit()

    def set_task_name(self, task_id: str, name: str) -> bool:
        """Store the short task name shown in the list; the query itself never changes."""
        with self._lock:
            cursor = self._conn.execute(
                "UPDATE tasks SET name = ?, updated_at = ? WHERE task_id = ?",
                (name, datetime.now(UTC).isoformat(), task_id),
            )
            self._conn.commit()
            return (cursor.rowcount or 0) > 0

    def get_task(self, task_id: str) -> dict[str, Any] | None:
        with self._lock:
            task = self._conn.execute(
                """
                SELECT t.task_id, t.query, t.name, t.provider, t.status, t.created_at, t.updated_at,
                       t.session_id, t.model_id, t.mode, m.name AS model_name
                FROM tasks t
                LEFT JOIN models m ON m.model_id = t.model_id
                WHERE t.task_id = ?
                """,
                (task_id,),
            ).fetchone()
            if task is None:
                return None

            events = self._conn.execute(
                """
                SELECT event_id, task_id, timestamp, category, title, source, data, collapsed
                FROM events
                WHERE task_id = ?
                ORDER BY id ASC
                """,
                (task_id,),
            ).fetchall()

            return {
                "task_id": task["task_id"],
                "query": task["query"],
                "name": task["name"] or "",
                "provider": task["provider"],
                "status": task["status"],
                "created_at": self._parse_datetime(task["created_at"]),
                "updated_at": self._parse_datetime(task["updated_at"]),
                "session_id": task["session_id"],
                "model_id": task["model_id"],
                "model_name": task["model_name"],
                "mode": task["mode"],
                "events": [self._event_to_dict(row) for row in events],
            }

    def list_tasks(self, session_id: str | None = None) -> list[dict[str, Any]]:
        with self._lock:
            if session_id:
                rows = self._conn.execute(
                    """
                    SELECT t.task_id, t.query, t.name, t.status, t.provider, t.created_at,
                           t.updated_at, t.session_id, t.model_id, t.mode, m.name AS model_name,
                           t.result, COUNT(e.event_id) AS event_count
                    FROM tasks t
                    LEFT JOIN events e ON t.task_id = e.task_id
                    LEFT JOIN models m ON m.model_id = t.model_id
                    WHERE t.session_id = ?
                    GROUP BY t.task_id, t.query, t.name, t.status, t.provider, t.created_at,
                             t.updated_at, t.session_id, t.model_id, t.mode, m.name, t.result
                    ORDER BY t.created_at ASC, t.task_id ASC
                    """,
                    (session_id,),
                ).fetchall()
            else:
                rows = self._conn.execute(
                    """
                    SELECT t.task_id, t.query, t.name, t.status, t.provider, t.created_at,
                           t.updated_at, t.session_id, t.model_id, t.mode, m.name AS model_name,
                           t.result, COUNT(e.event_id) AS event_count
                    FROM tasks t
                    LEFT JOIN events e ON t.task_id = e.task_id
                    LEFT JOIN models m ON m.model_id = t.model_id
                    GROUP BY t.task_id, t.query, t.name, t.status, t.provider, t.created_at,
                             t.updated_at, t.session_id, t.model_id, t.mode, m.name, t.result
                    ORDER BY t.created_at ASC, t.task_id ASC
                    """
                ).fetchall()
            return [
                {
                    "task_id": row["task_id"],
                    "query": row["query"],
                    "name": row["name"] or "",
                    "status": row["status"],
                    "provider": row["provider"],
                    "created_at": self._parse_datetime(row["created_at"]),
                    "updated_at": self._parse_datetime(row["updated_at"]),
                    "session_id": row["session_id"],
                    "model_id": row["model_id"],
                    "model_name": row["model_name"],
                    "mode": row["mode"],
                    "event_count": int(row["event_count"]),
                    "result": row["result"] or "",
                }
                for row in rows
            ]

    def list_unfinished_tasks(self) -> list[dict[str, Any]]:
        """Tasks still marked in flight by whatever process last wrote them.

        ``running`` and ``waiting`` both mean "a thread owns this row" to the writer
        (a task parked on a confirmation is still in flight, ADR 0006 D10). After a
        restart no thread owns them any more, which is exactly what the startup
        recovery scan looks for.
        """
        with self._lock:
            rows = self._conn.execute(
                """
                SELECT task_id, query, name, status, provider, created_at, updated_at,
                       session_id, model_id, mode, result, resume_count
                FROM tasks
                WHERE status IN (?, ?)
                ORDER BY created_at ASC, task_id ASC
                """,
                (TaskStatus.RUNNING.value, TaskStatus.WAITING.value),
            ).fetchall()
            return [
                {
                    "task_id": row["task_id"],
                    "query": row["query"],
                    "name": row["name"] or "",
                    "status": row["status"],
                    "provider": row["provider"],
                    "created_at": self._parse_datetime(row["created_at"]),
                    "updated_at": self._parse_datetime(row["updated_at"]),
                    "session_id": row["session_id"],
                    "model_id": row["model_id"],
                    "mode": row["mode"],
                    "result": row["result"] or "",
                    "resume_count": int(row["resume_count"] or 0),
                }
                for row in rows
            ]

    def increase_resume_count(self, task_id: str) -> int:
        """Count one recovery attempt for a task and return the running total."""
        with self._lock:
            self._conn.execute(
                """
                UPDATE tasks
                SET resume_count = COALESCE(resume_count, 0) + 1, updated_at = ?
                WHERE task_id = ?
                """,
                (datetime.now(UTC).isoformat(), task_id),
            )
            self._conn.commit()
            row = self._conn.execute(
                "SELECT resume_count FROM tasks WHERE task_id = ?",
                (task_id,),
            ).fetchone()
            return int(row["resume_count"] or 0) if row is not None else 0

    def reset_resume_count(self, task_id: str) -> None:
        """Clear a task's retry budget after a resume that got somewhere.

        The budget exists for tasks that are stuck, not for tasks that keep being
        interrupted while doing real work (see ``task_recovery``).
        """
        with self._lock:
            self._conn.execute(
                "UPDATE tasks SET resume_count = 0 WHERE task_id = ?",
                (task_id,),
            )
            self._conn.commit()

    def get_events(self, task_id: str) -> list[dict[str, Any]]:
        with self._lock:
            rows = self._conn.execute(
                """
                SELECT event_id, task_id, timestamp, category, title, source, data, collapsed
                FROM events
                WHERE task_id = ?
                ORDER BY id ASC
                """,
                (task_id,),
            ).fetchall()
            return [self._event_to_dict(row) for row in rows]

    def recent_events_of_category(
        self, task_id: str, category: str, limit: int = 5
    ) -> list[dict[str, Any]]:
        """The newest events of one category, newest first.

        For callers that read a single figure out of an event - the context meter
        reads token usage - replaying the whole log would decode every tool result
        the task ever produced just to look at the last one.
        """
        with self._lock:
            rows = self._conn.execute(
                """
                SELECT event_id, task_id, timestamp, category, title, source, data, collapsed
                FROM events
                WHERE task_id = ? AND category = ?
                ORDER BY id DESC
                LIMIT ?
                """,
                (task_id, category, max(1, int(limit))),
            ).fetchall()
            return [self._event_to_dict(row) for row in rows]

    def get_events_since(
        self,
        task_id: str,
        since_event_id: str | None,
    ) -> list[dict[str, Any]]:
        with self._lock:
            if not since_event_id:
                rows = self._conn.execute(
                    """
                    SELECT event_id, task_id, timestamp, category, title, source, data, collapsed
                    FROM events
                    WHERE task_id = ?
                    ORDER BY id ASC
                    """,
                    (task_id,),
                ).fetchall()
                return [self._event_to_dict(row) for row in rows]

            row = self._conn.execute(
                "SELECT id FROM events WHERE task_id = ? AND event_id = ?",
                (task_id, since_event_id),
            ).fetchone()
            since_id = row["id"] if row else 0

            rows = self._conn.execute(
                """
                SELECT event_id, task_id, timestamp, category, title, source, data, collapsed
                FROM events
                WHERE task_id = ? AND id > ?
                ORDER BY id ASC
                """,
                (task_id, since_id),
            ).fetchall()
            return [self._event_to_dict(row) for row in rows]

    def list_events_paginated(
        self,
        task_id: str,
        offset: int,
        limit: int,
    ) -> tuple[list[dict[str, Any]], int]:
        with self._lock:
            total_row = self._conn.execute(
                "SELECT COUNT(*) AS total FROM events WHERE task_id = ?",
                (task_id,),
            ).fetchone()
            if total_row is None:
                return [], 0
            total = int(total_row["total"])

            offset = max(offset, 0)

            rows = self._conn.execute(
                """
                SELECT event_id, task_id, timestamp, category, title, source, data, collapsed
                FROM events
                WHERE task_id = ?
                ORDER BY id ASC
                LIMIT ? OFFSET ?
                """,
                (task_id, limit, offset),
            ).fetchall()

            start = offset
            if start >= total:
                return [], total

            return (
                [self._event_to_dict(row) for row in rows],
                total,
            )

    def append_event(self, task_id: str, event: TaskEvent) -> None:
        with self._lock:
            task_exists = self._conn.execute(
                "SELECT 1 FROM tasks WHERE task_id = ?",
                (task_id,),
            ).fetchone()
            if task_exists is None:
                return

            self._conn.execute(
                """
                INSERT INTO events (
                    event_id, task_id, timestamp, category, title, source, data, collapsed
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    event.event_id,
                    event.task_id,
                    event.timestamp.isoformat(),
                    event.category.value,
                    event.title,
                    event.source,
                    json.dumps(event.data, default=str, ensure_ascii=False),
                    int(event.collapsed),
                ),
            )
            self._conn.execute(
                "UPDATE tasks SET updated_at = ? WHERE task_id = ?",
                (event.timestamp.isoformat(), task_id),
            )
            self._conn.commit()

    def set_task_status(self, task_id: str, status: TaskStatus) -> None:
        """Move a task between non-final states.

        Needed because a task can now be in flight *while blocked on a user
        confirmation* (``TaskStatus.WAITING``, see ADR 0006 D10). ``finish_task``
        is for the final state only and would also overwrite ``result``.
        """
        with self._lock:
            self._conn.execute(
                """
                UPDATE tasks
                SET status = ?, updated_at = ?
                WHERE task_id = ?
                """,
                (status, datetime.now(UTC).isoformat(), task_id),
            )
            self._conn.commit()

    def finish_task(
        self,
        task_id: str,
        success: bool,
        result: str | None = None,
        status: TaskStatus | None = None,
    ) -> None:
        """Record a task's final state, unless the user already settled it.

        ``_USER_SETTLED_STATUSES`` wins over what the agent thread reports: after a
        stop click that thread keeps running until its in-flight model request returns
        (ADR 0019 D6) and may then report a result - even a successful one - long
        after the click. Letting that write win would put "running"/"success" back on
        a row the user has already ended; the result itself is still worth keeping.
        """
        final_status = status if status is not None else (TaskStatus.SUCCESS if success else TaskStatus.FAILED)
        with self._lock:
            current = self._conn.execute(
                "SELECT status FROM tasks WHERE task_id = ?", (task_id,)
            ).fetchone()
            if current is not None and str(current["status"]) in _USER_SETTLED_STATUSES:
                final_status = TaskStatus(str(current["status"]))
            self._conn.execute(
                """
                UPDATE tasks
                SET status = ?, updated_at = ?, result = ?
                WHERE task_id = ?
                """,
                (
                    final_status,
                    datetime.now(UTC).isoformat(),
                    result if result is not None else "",
                    task_id,
                ),
            )
            self._conn.commit()
