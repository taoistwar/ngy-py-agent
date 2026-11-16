"""Forking a session: copying one conversation's turns into a new session.

A fork is a branch, not a move: the original session keeps every task it had, and
the new one gets a copy of the chosen task plus all of the turns before it, so its
next task starts from the same transcript.
"""

from __future__ import annotations

import sqlite3
from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

from agent.models import TaskStatus

# ``sessions.name`` is capped to the API schema's length; a fork's name comes from the
# task it branches at, which can be a whole query.
_FORK_NAME_MAX_LENGTH = 120


class _ForkMixin:
    """Copy a session's tasks up to a fork point into a fresh session."""

    def fork_session_through_task(
        self,
        task_id: str,
        name: str | None = None,
    ) -> dict[str, Any] | None:
        """Copy the task and every earlier task of its session into a new session.

        Task order, timestamps, names and events are copied so the new conversation
        reads exactly like the turns it branched from, and its next task starts with
        that transcript as history. The original session is left untouched.

        Returns ``None`` when the task (or the session it belongs to) is gone. A task
        that is still in flight is refused by the caller, because its event log is
        still being written and a copy of it would be a snapshot of half a turn.
        """
        with self._lock:
            task = self._conn.execute(
                """
                SELECT task_id, session_id, query, name
                FROM tasks
                WHERE task_id = ?
                """,
                (task_id,),
            ).fetchone()
            if task is None or not task["session_id"]:
                return None

            source_session = self._conn.execute(
                "SELECT workspace_id FROM sessions WHERE session_id = ?",
                (task["session_id"],),
            ).fetchone()
            workspace_id = source_session["workspace_id"] if source_session is not None else None

            # Same order as ``list_tasks``: the branch covers the rows above this one.
            rows = self._conn.execute(
                """
                SELECT task_id, query, name, provider, status, created_at, updated_at,
                       model_id, mode, result
                FROM tasks
                WHERE session_id = ?
                ORDER BY created_at ASC, task_id ASC
                """,
                (task["session_id"],),
            ).fetchall()
            target_index = next(
                (index for index, row in enumerate(rows) if row["task_id"] == task_id),
                None,
            )
            if target_index is None:
                return None
            history = rows[: target_index + 1]

            now = datetime.now(UTC).isoformat()
            new_session_id = str(uuid4())
            new_tasks: list[tuple[Any, ...]] = []
            new_events: list[tuple[Any, ...]] = []
            branched_task_id = ""

            try:
                self._conn.execute(
                    """
                    INSERT INTO sessions (session_id, name, created_at, updated_at, workspace_id)
                    VALUES (?, ?, ?, ?, ?)
                    """,
                    (new_session_id, _fork_session_name(name, task), now, now, workspace_id),
                )
                for row in history:
                    new_task_id = str(uuid4())
                    if row["task_id"] == task_id:
                        branched_task_id = new_task_id
                    new_tasks.append(
                        (
                            new_task_id,
                            row["query"],
                            row["name"] or "",
                            row["provider"],
                            _fork_status(row["status"]),
                            row["created_at"],
                            row["updated_at"],
                            new_session_id,
                            row["model_id"],
                            row["mode"],
                            row["result"] or "",
                        )
                    )
                    for event in self._conn.execute(
                        """
                        SELECT timestamp, category, title, source, data, collapsed
                        FROM events
                        WHERE task_id = ?
                        ORDER BY id ASC
                        """,
                        (row["task_id"],),
                    ).fetchall():
                        new_events.append(
                            (
                                str(uuid4()),
                                new_task_id,
                                event["timestamp"],
                                event["category"],
                                event["title"],
                                event["source"],
                                event["data"],
                                int(event["collapsed"]),
                            )
                        )
                self._conn.executemany(
                    """
                    INSERT INTO tasks (
                        task_id, query, name, provider, status, created_at, updated_at,
                        session_id, model_id, mode, result
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    new_tasks,
                )
                self._conn.executemany(
                    """
                    INSERT INTO events (
                        event_id, task_id, timestamp, category, title, source, data, collapsed
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    new_events,
                )
                self._conn.commit()
            except Exception:
                self._conn.rollback()
                raise

        return {
            "session_id": new_session_id,
            "name": _fork_session_name(name, task),
            "task_id": branched_task_id,
            "source_session_id": task["session_id"],
            "source_task_id": task_id,
            "copied_task_count": len(new_tasks),
            "event_count": len(new_events),
        }


def _fork_session_name(name: str | None, task: sqlite3.Row) -> str:
    """The branch's name: what the caller asked for, else the task it branched at."""
    explicit = (name or "").strip()
    if explicit:
        return explicit[:_FORK_NAME_MAX_LENGTH]
    label = (task["name"] or "").strip() or " ".join(str(task["query"] or "").split())
    return (label or "Fork")[:_FORK_NAME_MAX_LENGTH]


def _fork_status(status: str) -> str:
    """Status to store on a copied task.

    A copy is history, not work: leaving ``running``/``waiting`` on it would make the
    startup recovery scan pick the copy up and run the same turn a second time.
    """
    if status in (TaskStatus.RUNNING.value, TaskStatus.WAITING.value):
        return TaskStatus.STOPPED.value
    return status
