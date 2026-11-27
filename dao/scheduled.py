"""Scheduled tasks: their definitions, their pause switch and the runs they produced.

Two tables. ``schedules`` holds what should run and when ("0 9 * * *" plus the prompt);
``schedule_runs`` holds one row per attempt, pointing at the session and task the
attempt created. The run row records only the **launch** outcome - whether a task was
created - while the task's own status is joined in when the run is read, so "did this
run succeed" is never a second copy that can disagree with the task it describes.
"""

from __future__ import annotations

import sqlite3
from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

# Launch outcomes of one run. ``started`` means a task exists and owns the outcome.
RUN_STARTED = "started"
RUN_FAILED = "failed"
RUN_SKIPPED = "skipped"

TRIGGER_CRON = "cron"
TRIGGER_MANUAL = "manual"

# Columns an update may rewrite. Everything else (ids, timestamps, the fire marker)
# belongs to the store or the scheduler.
_UPDATABLE_FIELDS = (
    "name",
    "cron",
    "prompt",
    "agent_id",
    "model_id",
    "workspace_id",
    "permission_mode",
    "enabled",
    "recurring",
)

_RUN_COLUMNS = """
    r.run_id, r.schedule_id, r.trigger, r.session_id, r.task_id, r.status, r.error,
    r.created_at, s.name AS schedule_name, t.status AS task_status, t.query AS task_query
"""


class _ScheduleMixin:
    """Scheduled task definitions and their run records."""

    def _schedule_to_dict(self, row: sqlite3.Row) -> dict[str, Any]:
        return {
            "schedule_id": row["schedule_id"],
            "name": row["name"] or "",
            "cron": row["cron"],
            "prompt": row["prompt"],
            "agent_id": row["agent_id"],
            "model_id": row["model_id"],
            "workspace_id": row["workspace_id"],
            # Empty means "follow the global confirmation mode".
            "permission_mode": row["permission_mode"] or "",
            "enabled": bool(row["enabled"]),
            "recurring": bool(row["recurring"]),
            "last_fired": row["last_fired"] or "",
            "last_run_at": self._parse_datetime(row["last_run_at"])
            if row["last_run_at"]
            else None,
            "created_at": self._parse_datetime(row["created_at"]),
            "updated_at": self._parse_datetime(row["updated_at"]),
        }

    def _run_to_dict(self, row: sqlite3.Row) -> dict[str, Any]:
        return {
            "run_id": row["run_id"],
            "schedule_id": row["schedule_id"],
            "schedule_name": row["schedule_name"] or "",
            "trigger": row["trigger"],
            "status": row["status"],
            "task_id": row["task_id"] or "",
            "session_id": row["session_id"] or "",
            # ``None`` when the task no longer exists (deleted, or never created).
            "task_status": row["task_status"],
            "task_query": row["task_query"],
            "error": row["error"] or "",
            "created_at": self._parse_datetime(row["created_at"]),
        }

    # ------------------------------------------------------------------ schedules

    def create_schedule(
        self,
        *,
        cron: str,
        prompt: str,
        name: str = "",
        agent_id: str = "build",
        model_id: str | None = None,
        workspace_id: str | None = None,
        permission_mode: str = "",
        enabled: bool = True,
        recurring: bool = True,
    ) -> str:
        schedule_id = str(uuid4())
        now = datetime.now(UTC).isoformat()
        with self._lock:
            self._conn.execute(
                """
                INSERT INTO schedules (
                    schedule_id, name, cron, prompt, agent_id, model_id, workspace_id,
                    permission_mode, enabled, recurring, last_fired, last_run_at,
                    created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, NULL, NULL, ?, ?)
                """,
                (
                    schedule_id,
                    name,
                    cron,
                    prompt,
                    agent_id,
                    model_id,
                    workspace_id,
                    permission_mode,
                    int(bool(enabled)),
                    int(bool(recurring)),
                    now,
                    now,
                ),
            )
            self._conn.commit()
        return schedule_id

    def get_schedule(self, schedule_id: str) -> dict[str, Any] | None:
        with self._lock:
            row = self._conn.execute(
                "SELECT * FROM schedules WHERE schedule_id = ?",
                (schedule_id,),
            ).fetchone()
        return None if row is None else self._schedule_to_dict(row)

    def list_schedules(self) -> list[dict[str, Any]]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT * FROM schedules ORDER BY created_at ASC, schedule_id ASC"
            ).fetchall()
        return [self._schedule_to_dict(row) for row in rows]

    def list_enabled_schedules(self) -> list[dict[str, Any]]:
        """The lists the scheduler walks every tick; a paused one is not due, ever."""
        with self._lock:
            rows = self._conn.execute(
                "SELECT * FROM schedules WHERE enabled = 1 ORDER BY created_at ASC, schedule_id ASC"
            ).fetchall()
        return [self._schedule_to_dict(row) for row in rows]

    def update_schedule(self, schedule_id: str, **fields: Any) -> bool:
        """Rewrite the given fields; unknown names are ignored, not written."""
        changes = {
            key: int(bool(value)) if key in ("enabled", "recurring") else value
            for key, value in fields.items()
            if key in _UPDATABLE_FIELDS
        }
        if not changes:
            return self.get_schedule(schedule_id) is not None
        assignments = ", ".join(f"{key} = ?" for key in changes)
        values = list(changes.values())
        with self._lock:
            cursor = self._conn.execute(
                f"UPDATE schedules SET {assignments}, updated_at = ? WHERE schedule_id = ?",
                (*values, datetime.now(UTC).isoformat(), schedule_id),
            )
            self._conn.commit()
            return (cursor.rowcount or 0) > 0

    def delete_schedule(self, schedule_id: str) -> bool:
        """Delete the definition, its runs, and leave the tasks those runs started.

        The tasks are the record of what happened; deleting the schedule is a
        decision about the future, not permission to erase the past.
        """
        with self._lock:
            self._conn.execute(
                "DELETE FROM schedule_runs WHERE schedule_id = ?", (schedule_id,)
            )
            cursor = self._conn.execute(
                "DELETE FROM schedules WHERE schedule_id = ?", (schedule_id,)
            )
            self._conn.commit()
            return (cursor.rowcount or 0) > 0

    def claim_schedule_fire(self, schedule_id: str, minute_marker: str) -> bool:
        """Mark this minute as fired, or report that somebody already did.

        One conditional UPDATE instead of "read, then write": two ticks (or a tick and
        a restarting process) cannot both observe the old marker and both fire.
        """
        now = datetime.now(UTC).isoformat()
        with self._lock:
            cursor = self._conn.execute(
                """
                UPDATE schedules
                SET last_fired = ?, last_run_at = ?, updated_at = ?
                WHERE schedule_id = ?
                  AND (last_fired IS NULL OR last_fired != ?)
                """,
                (minute_marker, now, now, schedule_id, minute_marker),
            )
            self._conn.commit()
            return (cursor.rowcount or 0) > 0

    # ---------------------------------------------------------------- schedule runs

    def create_schedule_run(
        self,
        schedule_id: str,
        trigger: str,
        *,
        session_id: str = "",
        task_id: str = "",
        status: str = RUN_STARTED,
        error: str = "",
    ) -> dict[str, Any]:
        run_id = str(uuid4())
        now = datetime.now(UTC).isoformat()
        with self._lock:
            self._conn.execute(
                """
                INSERT INTO schedule_runs (
                    run_id, schedule_id, trigger, session_id, task_id, status, error, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (run_id, schedule_id, trigger, session_id, task_id, status, error, now),
            )
            self._conn.commit()
            row = self._conn.execute(
                f"""
                SELECT {_RUN_COLUMNS}
                FROM schedule_runs r
                LEFT JOIN schedules s ON s.schedule_id = r.schedule_id
                LEFT JOIN tasks t ON t.task_id = r.task_id AND r.task_id != ''
                WHERE r.run_id = ?
                """,
                (run_id,),
            ).fetchone()
        return self._run_to_dict(row)

    def list_schedule_runs(self, schedule_id: str, limit: int = 50) -> list[dict[str, Any]]:
        with self._lock:
            rows = self._conn.execute(
                f"""
                SELECT {_RUN_COLUMNS}
                FROM schedule_runs r
                LEFT JOIN schedules s ON s.schedule_id = r.schedule_id
                LEFT JOIN tasks t ON t.task_id = r.task_id AND r.task_id != ''
                WHERE r.schedule_id = ?
                ORDER BY r.created_at DESC
                LIMIT ?
                """,
                (schedule_id, max(1, int(limit))),
            ).fetchall()
        return [self._run_to_dict(row) for row in rows]

    def list_running_schedule_runs(self) -> list[dict[str, Any]]:
        """Runs whose task is still in flight: what "running now" is made of.

        ``waiting`` counts - a task parked on a confirmation is still running, and
        hiding it would hide exactly the run that needs a human.
        """
        with self._lock:
            rows = self._conn.execute(
                f"""
                SELECT {_RUN_COLUMNS}
                FROM schedule_runs r
                JOIN tasks t ON t.task_id = r.task_id
                JOIN schedules s ON s.schedule_id = r.schedule_id
                WHERE r.status = ? AND t.status IN ('running', 'waiting')
                ORDER BY r.created_at ASC
                """,
                (RUN_STARTED,),
            ).fetchall()
        return [self._run_to_dict(row) for row in rows]

    def has_active_schedule_run(self, schedule_id: str) -> bool:
        """Whether this schedule already has a task in flight."""
        with self._lock:
            row = self._conn.execute(
                """
                SELECT 1
                FROM schedule_runs r
                JOIN tasks t ON t.task_id = r.task_id
                WHERE r.schedule_id = ? AND r.status = ? AND t.status IN ('running', 'waiting')
                LIMIT 1
                """,
                (schedule_id, RUN_STARTED),
            ).fetchone()
        return row is not None
