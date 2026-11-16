"""Sessions and workspaces: the context a task runs in.

A session is the conversation a task runs in; a workspace is the folder that
conversation starts in.
"""

from __future__ import annotations

import sqlite3
from datetime import UTC, datetime
from typing import Any
from uuid import uuid4


class _SessionMixin:
    """Session and workspace persistence."""

    def _session_to_dict(self, row: sqlite3.Row) -> dict[str, Any]:
        return {
            "session_id": row["session_id"],
            "name": row["name"],
            "workspace_id": row["workspace_id"] if "workspace_id" in row.keys() else None,
            "created_at": self._parse_datetime(row["created_at"]),
            "updated_at": self._parse_datetime(row["updated_at"]),
            "task_count": int(row["task_count"]) if "task_count" in row.keys() else 0,
        }

    def ensure_default_session(self) -> str:
        with self._lock:
            row = self._conn.execute("SELECT session_id FROM sessions ORDER BY created_at ASC LIMIT 1").fetchone()
        if row is not None:
            return str(row["session_id"])
        return self.create_session("Default Session")

    def _assign_orphan_tasks(self, session_id: str) -> int:
        with self._lock:
            cursor = self._conn.execute(
                "UPDATE tasks SET session_id = ? WHERE session_id IS NULL OR session_id = ''",
                (session_id,),
            )
            self._conn.commit()
            return int(cursor.rowcount or 0)

    def create_session(self, name: str, workspace_id: str | None = None) -> str:
        session_id = str(uuid4())
        now = datetime.now(UTC).isoformat()
        with self._lock:
            self._conn.execute(
                """
                INSERT INTO sessions (session_id, name, created_at, updated_at, workspace_id)
                VALUES (?, ?, ?, ?, ?)
                """,
                (session_id, name, now, now, workspace_id),
            )
            self._conn.commit()
        return session_id

    def get_session(self, session_id: str) -> dict[str, Any] | None:
        with self._lock:
            row = self._conn.execute(
                """
                SELECT s.session_id, s.name, s.workspace_id, s.created_at, s.updated_at,
                       COUNT(t.task_id) AS task_count
                FROM sessions s
                LEFT JOIN tasks t ON t.session_id = s.session_id
                WHERE s.session_id = ?
                GROUP BY s.session_id, s.name, s.workspace_id, s.created_at, s.updated_at
                """,
                (session_id,),
            ).fetchone()
        if row is None:
            return None
        return self._session_to_dict(row)

    def list_sessions(self) -> list[dict[str, Any]]:
        with self._lock:
            rows = self._conn.execute(
                """
                SELECT s.session_id, s.name, s.workspace_id, s.created_at, s.updated_at,
                       COUNT(t.task_id) AS task_count
                FROM sessions s
                LEFT JOIN tasks t ON t.session_id = s.session_id
                GROUP BY s.session_id, s.name, s.workspace_id, s.created_at, s.updated_at
                ORDER BY s.created_at ASC
                """
            ).fetchall()
        return [self._session_to_dict(row) for row in rows]

    def rename_session(self, session_id: str, name: str) -> bool:
        with self._lock:
            cursor = self._conn.execute(
                "UPDATE sessions SET name = ?, updated_at = ? WHERE session_id = ?",
                (name, datetime.now(UTC).isoformat(), session_id),
            )
            self._conn.commit()
            return (cursor.rowcount or 0) > 0

    def delete_session(self, session_id: str) -> bool:
        with self._lock:
            self._conn.execute(
                "DELETE FROM events WHERE task_id IN (SELECT task_id FROM tasks WHERE session_id = ?)",
                (session_id,),
            )
            self._conn.execute("DELETE FROM tasks WHERE session_id = ?", (session_id,))
            cursor = self._conn.execute("DELETE FROM sessions WHERE session_id = ?", (session_id,))
            self._conn.commit()
            return (cursor.rowcount or 0) > 0

    def _workspace_to_dict(self, row: sqlite3.Row) -> dict[str, Any]:
        return {
            "workspace_id": row["workspace_id"],
            "name": row["name"],
            "root_path": row["root_path"],
            "created_at": self._parse_datetime(row["created_at"]),
            "updated_at": self._parse_datetime(row["updated_at"]),
            "session_count": int(row["session_count"]) if "session_count" in row.keys() else 0,
        }

    def create_workspace(self, name: str, root_path: str) -> str:
        workspace_id = str(uuid4())
        now = datetime.now(UTC).isoformat()
        with self._lock:
            self._conn.execute(
                """
                INSERT INTO workspaces (workspace_id, name, root_path, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?)
                """,
                (workspace_id, name, root_path, now, now),
            )
            self._conn.commit()
        return workspace_id

    def list_workspaces(self) -> list[dict[str, Any]]:
        with self._lock:
            rows = self._conn.execute(
                """
                SELECT w.workspace_id, w.name, w.root_path, w.created_at, w.updated_at,
                       COUNT(s.session_id) AS session_count
                FROM workspaces w
                LEFT JOIN sessions s ON s.workspace_id = w.workspace_id
                GROUP BY w.workspace_id, w.name, w.root_path, w.created_at, w.updated_at
                ORDER BY w.created_at ASC
                """
            ).fetchall()
        return [self._workspace_to_dict(row) for row in rows]

    def get_workspace(self, workspace_id: str) -> dict[str, Any] | None:
        with self._lock:
            row = self._conn.execute(
                """
                SELECT w.workspace_id, w.name, w.root_path, w.created_at, w.updated_at,
                       COUNT(s.session_id) AS session_count
                FROM workspaces w
                LEFT JOIN sessions s ON s.workspace_id = w.workspace_id
                WHERE w.workspace_id = ?
                GROUP BY w.workspace_id, w.name, w.root_path, w.created_at, w.updated_at
                """,
                (workspace_id,),
            ).fetchone()
        if row is None:
            return None
        return self._workspace_to_dict(row)

    def update_workspace(
        self,
        workspace_id: str,
        name: str | None = None,
        root_path: str | None = None,
    ) -> dict[str, Any] | None:
        current = self.get_workspace(workspace_id)
        if current is None:
            return None
        merged_name = name if name is not None else current["name"]
        merged_root = root_path if root_path is not None else current["root_path"]
        with self._lock:
            self._conn.execute(
                """
                UPDATE workspaces
                SET name = ?, root_path = ?, updated_at = ?
                WHERE workspace_id = ?
                """,
                (merged_name, merged_root, datetime.now(UTC).isoformat(), workspace_id),
            )
            self._conn.commit()
        return self.get_workspace(workspace_id)

    def delete_workspace(self, workspace_id: str) -> bool:
        with self._lock:
            self._conn.execute(
                "UPDATE sessions SET workspace_id = NULL WHERE workspace_id = ?",
                (workspace_id,),
            )
            cursor = self._conn.execute(
                "DELETE FROM workspaces WHERE workspace_id = ?",
                (workspace_id,),
            )
            self._conn.commit()
            return (cursor.rowcount or 0) > 0

    def set_session_workspace(self, session_id: str, workspace_id: str | None) -> bool:
        with self._lock:
            cursor = self._conn.execute(
                "UPDATE sessions SET workspace_id = ?, updated_at = ? WHERE session_id = ?",
                (workspace_id, datetime.now(UTC).isoformat(), session_id),
            )
            self._conn.commit()
            return (cursor.rowcount or 0) > 0
