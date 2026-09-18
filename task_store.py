"""SQLite persistence for tasks, sessions, models, events and global settings."""

from __future__ import annotations

import json
import sqlite3
import threading
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from uuid import uuid4

from agent.models import TaskEvent, TaskStatus

ROOT_DIR = Path(__file__).resolve().parent
TASK_DB_PATH = ROOT_DIR / "monitor_tasks.db"
TASK_RETENTION_DEFAULT_DAYS = 36600


class _SqliteTaskStore:
    """SQLite-based task and event persistence."""

    def __init__(self, db_path: Path = TASK_DB_PATH) -> None:
        self._db_path = Path(db_path)
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(self._db_path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._lock = threading.Lock()
        self._init_schema()

    @staticmethod
    def _parse_datetime(value: str | None) -> datetime:
        if not value:
            return datetime.now(UTC)
        return datetime.fromisoformat(value)

    @staticmethod
    def _event_to_dict(row: sqlite3.Row) -> dict[str, Any]:
        return {
            "event_id": row["event_id"],
            "task_id": row["task_id"],
            "timestamp": _SqliteTaskStore._parse_datetime(row["timestamp"]),
            "category": row["category"],
            "title": row["title"],
            "source": row["source"],
            "data": json.loads(row["data"] or "{}"),
            "collapsed": bool(row["collapsed"]),
        }

    def _init_schema(self) -> None:
        with self._lock:
            self._conn.execute("PRAGMA foreign_keys = ON")
            self._conn.execute(
                """
                CREATE TABLE IF NOT EXISTS sessions (
                    session_id TEXT PRIMARY KEY,
                    name TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )
                """
            )
            self._conn.execute(
                """
                CREATE TABLE IF NOT EXISTS workspaces (
                    workspace_id TEXT PRIMARY KEY,
                    name TEXT NOT NULL,
                    root_path TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )
                """
            )
            self._conn.execute(
                """
                CREATE TABLE IF NOT EXISTS agents (
                    agent_id TEXT PRIMARY KEY,
                    name TEXT NOT NULL,
                    description TEXT NOT NULL DEFAULT '',
                    system_prompt TEXT NOT NULL DEFAULT '',
                    tool_names TEXT,
                    skill_names TEXT NOT NULL DEFAULT '[]',
                    mcp_servers TEXT NOT NULL DEFAULT '[]',
                    is_builtin INTEGER NOT NULL DEFAULT 0,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )
                """
            )
            self._conn.execute(
                """
                CREATE TABLE IF NOT EXISTS tasks (
                    task_id TEXT PRIMARY KEY,
                    query TEXT NOT NULL,
                    provider TEXT NOT NULL,
                    status TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    session_id TEXT,
                    model_id TEXT,
                    mode TEXT NOT NULL DEFAULT 'build'
                )
                """
            )
            self._conn.execute(
                """
                CREATE TABLE IF NOT EXISTS models (
                    model_id TEXT PRIMARY KEY,
                    name TEXT NOT NULL,
                    provider TEXT NOT NULL,
                    base_url TEXT NOT NULL DEFAULT '',
                    api_key TEXT NOT NULL DEFAULT '',
                    supports_tool_calls INTEGER NOT NULL DEFAULT 1,
                    supports_image_input INTEGER NOT NULL DEFAULT 0,
                    thinking_mode INTEGER NOT NULL DEFAULT 0,
                    max_input_tokens INTEGER NOT NULL DEFAULT 0,
                    max_output_tokens INTEGER NOT NULL DEFAULT 0,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )
                """
            )
            self._conn.execute(
                """
                CREATE TABLE IF NOT EXISTS events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    event_id TEXT UNIQUE NOT NULL,
                    task_id TEXT NOT NULL REFERENCES tasks(task_id) ON DELETE CASCADE,
                    timestamp TEXT NOT NULL,
                    category TEXT NOT NULL,
                    title TEXT NOT NULL,
                    source TEXT NOT NULL,
                    data TEXT NOT NULL,
                    collapsed INTEGER NOT NULL DEFAULT 1
                )
                """
            )
            self._conn.execute(
                """
                CREATE TABLE IF NOT EXISTS settings (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )
                """
            )
            self._ensure_task_columns()
            self._ensure_session_columns()
            self._conn.execute("CREATE INDEX IF NOT EXISTS idx_events_task_id_id ON events(task_id, id)")
            self._conn.execute("CREATE INDEX IF NOT EXISTS idx_tasks_created_at ON tasks(created_at)")
            self._conn.execute("CREATE INDEX IF NOT EXISTS idx_tasks_session_id ON tasks(session_id)")
            self._conn.execute("CREATE INDEX IF NOT EXISTS idx_sessions_workspace_id ON sessions(workspace_id)")
            self._conn.commit()

        default_session_id = self.ensure_default_session()
        moved = self._assign_orphan_tasks(default_session_id)
        if moved > 0:
            print(f"[Session migration] assigned {moved} task(s) without session to default session.")

        self._seed_default_agents()

    def _ensure_task_columns(self) -> None:
        rows = self._conn.execute("PRAGMA table_info(tasks)").fetchall()
        existing = {row["name"] for row in rows}
        if "session_id" not in existing:
            self._conn.execute("ALTER TABLE tasks ADD COLUMN session_id TEXT")
        if "model_id" not in existing:
            self._conn.execute("ALTER TABLE tasks ADD COLUMN model_id TEXT")
        if "mode" not in existing:
            self._conn.execute("ALTER TABLE tasks ADD COLUMN mode TEXT NOT NULL DEFAULT 'build'")
        if "result" not in existing:
            self._conn.execute("ALTER TABLE tasks ADD COLUMN result TEXT")

    def _ensure_session_columns(self) -> None:
        rows = self._conn.execute("PRAGMA table_info(sessions)").fetchall()
        existing = {row["name"] for row in rows}
        if "workspace_id" not in existing:
            self._conn.execute("ALTER TABLE sessions ADD COLUMN workspace_id TEXT")

    def _seed_default_agents(self) -> None:
        """Insert the built-in build/ask/plan agents derived from the mode configs."""
        from agent.modes import MODE_CONFIGS

        now = datetime.now(UTC).isoformat()
        with self._lock:
            for name, config in MODE_CONFIGS.items():
                row = self._conn.execute(
                    "SELECT 1 FROM agents WHERE agent_id = ?",
                    (name,),
                ).fetchone()
                if row is not None:
                    continue
                tool_names = config.get("tool_names")
                self._conn.execute(
                    """
                    INSERT INTO agents (
                        agent_id, name, description, system_prompt,
                        tool_names, skill_names, mcp_servers, is_builtin,
                        created_at, updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        name,
                        config.get("label", name),
                        config.get("description", ""),
                        config.get("system_prompt", ""),
                        json.dumps(list(tool_names)) if tool_names is not None else None,
                        json.dumps(list(config.get("skills", []))),
                        json.dumps([]),
                        1,
                        now,
                        now,
                    ),
                )
            self._conn.commit()

    @staticmethod
    def _session_to_dict(row: sqlite3.Row) -> dict[str, Any]:
        return {
            "session_id": row["session_id"],
            "name": row["name"],
            "workspace_id": row["workspace_id"] if "workspace_id" in row.keys() else None,
            "created_at": _SqliteTaskStore._parse_datetime(row["created_at"]),
            "updated_at": _SqliteTaskStore._parse_datetime(row["updated_at"]),
            "task_count": int(row["task_count"]) if "task_count" in row.keys() else 0,
        }

    @staticmethod
    def _model_to_dict(row: sqlite3.Row) -> dict[str, Any]:
        return {
            "model_id": row["model_id"],
            "name": row["name"],
            "provider": row["provider"],
            "base_url": row["base_url"] or "",
            "api_key": row["api_key"] or "",
            "supports_tool_calls": bool(row["supports_tool_calls"]),
            "supports_image_input": bool(row["supports_image_input"]),
            "thinking_mode": bool(row["thinking_mode"]),
            "max_input_tokens": int(row["max_input_tokens"] or 0),
            "max_output_tokens": int(row["max_output_tokens"] or 0),
            "created_at": _SqliteTaskStore._parse_datetime(row["created_at"]),
            "updated_at": _SqliteTaskStore._parse_datetime(row["updated_at"]),
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
        return _SqliteTaskStore._session_to_dict(row)

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
        return [_SqliteTaskStore._session_to_dict(row) for row in rows]

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

    @staticmethod
    def _workspace_to_dict(row: sqlite3.Row) -> dict[str, Any]:
        return {
            "workspace_id": row["workspace_id"],
            "name": row["name"],
            "root_path": row["root_path"],
            "created_at": _SqliteTaskStore._parse_datetime(row["created_at"]),
            "updated_at": _SqliteTaskStore._parse_datetime(row["updated_at"]),
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
        return [_SqliteTaskStore._workspace_to_dict(row) for row in rows]

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
        return _SqliteTaskStore._workspace_to_dict(row)

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

    @staticmethod
    def _load_json(raw: str | None, default: Any) -> Any:
        if raw is None:
            return default
        try:
            return json.loads(raw)
        except (TypeError, ValueError):
            return default

    @classmethod
    def _agent_to_dict(cls, row: sqlite3.Row) -> dict[str, Any]:
        raw_tools = row["tool_names"]
        tool_names = None if raw_tools is None else cls._load_json(raw_tools, None)
        return {
            "agent_id": row["agent_id"],
            "name": row["name"],
            "description": row["description"] or "",
            "system_prompt": row["system_prompt"] or "",
            "tool_names": tool_names,
            "skill_names": cls._load_json(row["skill_names"], []) or [],
            "mcp_servers": cls._load_json(row["mcp_servers"], []) or [],
            "is_builtin": bool(row["is_builtin"]),
            "created_at": _SqliteTaskStore._parse_datetime(row["created_at"]),
            "updated_at": _SqliteTaskStore._parse_datetime(row["updated_at"]),
        }

    def list_agents(self) -> list[dict[str, Any]]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT * FROM agents ORDER BY created_at ASC, rowid ASC"
            ).fetchall()
        return [_SqliteTaskStore._agent_to_dict(row) for row in rows]

    def get_agent(self, agent_id: str) -> dict[str, Any] | None:
        with self._lock:
            row = self._conn.execute(
                "SELECT * FROM agents WHERE agent_id = ?",
                (agent_id,),
            ).fetchone()
        if row is None:
            return None
        return _SqliteTaskStore._agent_to_dict(row)

    def create_agent(self, payload: dict[str, Any]) -> dict[str, Any]:
        agent_id = str(uuid4())
        now = datetime.now(UTC).isoformat()
        tool_names = payload.get("tool_names")
        with self._lock:
            self._conn.execute(
                """
                INSERT INTO agents (
                    agent_id, name, description, system_prompt,
                    tool_names, skill_names, mcp_servers, is_builtin,
                    created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    agent_id,
                    payload.get("name") or "",
                    payload.get("description") or "",
                    payload.get("system_prompt") or "",
                    json.dumps(list(tool_names)) if tool_names is not None else None,
                    json.dumps(list(payload.get("skill_names") or [])),
                    json.dumps(list(payload.get("mcp_servers") or [])),
                    0,
                    now,
                    now,
                ),
            )
            self._conn.commit()
        created = self.get_agent(agent_id)
        assert created is not None
        return created

    def update_agent(self, agent_id: str, payload: dict[str, Any]) -> dict[str, Any] | None:
        current = self.get_agent(agent_id)
        if current is None:
            return None
        merged = {**current, **payload}
        tool_names = merged.get("tool_names")
        with self._lock:
            self._conn.execute(
                """
                UPDATE agents
                SET name = ?, description = ?, system_prompt = ?,
                    tool_names = ?, skill_names = ?, mcp_servers = ?, updated_at = ?
                WHERE agent_id = ?
                """,
                (
                    merged.get("name") or "",
                    merged.get("description") or "",
                    merged.get("system_prompt") or "",
                    json.dumps(list(tool_names)) if tool_names is not None else None,
                    json.dumps(list(merged.get("skill_names") or [])),
                    json.dumps(list(merged.get("mcp_servers") or [])),
                    datetime.now(UTC).isoformat(),
                    agent_id,
                ),
            )
            self._conn.commit()
        return self.get_agent(agent_id)

    def delete_agent(self, agent_id: str) -> bool:
        with self._lock:
            cursor = self._conn.execute("DELETE FROM agents WHERE agent_id = ?", (agent_id,))
            self._conn.commit()
            return (cursor.rowcount or 0) > 0

    def create_model(self, payload: dict[str, Any]) -> dict[str, Any]:
        model_id = str(uuid4())
        now = datetime.now(UTC).isoformat()
        with self._lock:
            self._conn.execute(
                """
                INSERT INTO models (
                    model_id, name, provider, base_url, api_key,
                    supports_tool_calls, supports_image_input, thinking_mode,
                    max_input_tokens, max_output_tokens, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    model_id,
                    payload["name"],
                    payload.get("provider") or "openai-compatible",
                    payload.get("base_url") or "",
                    payload.get("api_key") or "",
                    int(bool(payload.get("supports_tool_calls", True))),
                    int(bool(payload.get("supports_image_input", False))),
                    int(bool(payload.get("thinking_mode", False))),
                    int(payload.get("max_input_tokens") or 0),
                    int(payload.get("max_output_tokens") or 0),
                    now,
                    now,
                ),
            )
            self._conn.commit()
        created = self.get_model(model_id)
        assert created is not None
        return created

    def list_models(self) -> list[dict[str, Any]]:
        with self._lock:
            rows = self._conn.execute("SELECT * FROM models ORDER BY created_at ASC").fetchall()
        return [_SqliteTaskStore._model_to_dict(row) for row in rows]

    def get_model(self, model_id: str) -> dict[str, Any] | None:
        with self._lock:
            row = self._conn.execute("SELECT * FROM models WHERE model_id = ?", (model_id,)).fetchone()
        if row is None:
            return None
        return _SqliteTaskStore._model_to_dict(row)

    def update_model(self, model_id: str, payload: dict[str, Any]) -> dict[str, Any] | None:
        current = self.get_model(model_id)
        if current is None:
            return None

        merged = {**current, **{k: v for k, v in payload.items() if v is not None}}
        with self._lock:
            self._conn.execute(
                """
                UPDATE models
                SET name = ?, provider = ?, base_url = ?, api_key = ?,
                    supports_tool_calls = ?, supports_image_input = ?, thinking_mode = ?,
                    max_input_tokens = ?, max_output_tokens = ?, updated_at = ?
                WHERE model_id = ?
                """,
                (
                    merged["name"],
                    merged.get("provider") or "openai-compatible",
                    merged.get("base_url") or "",
                    merged.get("api_key") or "",
                    int(bool(merged.get("supports_tool_calls", True))),
                    int(bool(merged.get("supports_image_input", False))),
                    int(bool(merged.get("thinking_mode", False))),
                    int(merged.get("max_input_tokens") or 0),
                    int(merged.get("max_output_tokens") or 0),
                    datetime.now(UTC).isoformat(),
                    model_id,
                ),
            )
            self._conn.commit()
        return self.get_model(model_id)

    def delete_model(self, model_id: str) -> bool:
        with self._lock:
            cursor = self._conn.execute("DELETE FROM models WHERE model_id = ?", (model_id,))
            self._conn.commit()
            return (cursor.rowcount or 0) > 0

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
                    task_id, query, provider, status, created_at, updated_at, session_id, model_id, mode, result
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    task_id,
                    query,
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

    def get_task_retention_days(self) -> int | None:
        row = self._conn.execute(
            "SELECT value FROM settings WHERE key = ?",
            ("task_retention_days",),
        ).fetchone()
        if row is None:
            return None
        try:
            return int(row["value"])
        except (TypeError, ValueError):
            return None

    def set_task_retention_days(self, retention_days: int) -> None:
        now = datetime.now(UTC).isoformat()
        with self._lock:
            self._conn.execute(
                """
                INSERT INTO settings (key, value, updated_at)
                VALUES (?, ?, ?)
                ON CONFLICT(key) DO UPDATE SET value = excluded.value, updated_at = excluded.updated_at
                """,
                ("task_retention_days", str(retention_days), now),
            )
        self._conn.commit()

    def get_agent_max_steps(self) -> int | None:
        row = self._conn.execute(
            "SELECT value FROM settings WHERE key = ?",
            ("agent_max_steps",),
        ).fetchone()
        if row is None:
            return None
        try:
            return int(row["value"])
        except (TypeError, ValueError):
            return None

    def set_agent_max_steps(self, max_steps: int) -> None:
        now = datetime.now(UTC).isoformat()
        with self._lock:
            self._conn.execute(
                """
                INSERT INTO settings (key, value, updated_at)
                VALUES (?, ?, ?)
                ON CONFLICT(key) DO UPDATE SET value = excluded.value, updated_at = excluded.updated_at
                """,
                ("agent_max_steps", str(max_steps), now),
            )
        self._conn.commit()

    def get_skills_root(self) -> str | None:
        row = self._conn.execute(
            "SELECT value FROM settings WHERE key = ?",
            ("skills_root",),
        ).fetchone()
        if row is None:
            return None
        return str(row["value"])

    def set_skills_root(self, skills_root: str) -> None:
        now = datetime.now(UTC).isoformat()
        with self._lock:
            self._conn.execute(
                """
                INSERT INTO settings (key, value, updated_at)
                VALUES (?, ?, ?)
                ON CONFLICT(key) DO UPDATE SET value = excluded.value, updated_at = excluded.updated_at
                """,
                ("skills_root", skills_root, now),
            )
        self._conn.commit()

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

    def get_task(self, task_id: str) -> dict[str, Any] | None:
        with self._lock:
            task = self._conn.execute(
                """
                SELECT t.task_id, t.query, t.provider, t.status, t.created_at, t.updated_at,
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
                "provider": task["provider"],
                "status": task["status"],
                "created_at": self._parse_datetime(task["created_at"]),
                "updated_at": self._parse_datetime(task["updated_at"]),
                "session_id": task["session_id"],
                "model_id": task["model_id"],
                "model_name": task["model_name"],
                "mode": task["mode"],
                "events": [_SqliteTaskStore._event_to_dict(row) for row in events],
            }

    def list_tasks(self, session_id: str | None = None) -> list[dict[str, Any]]:
        with self._lock:
            if session_id:
                rows = self._conn.execute(
                    """
                    SELECT t.task_id, t.query, t.status, t.provider, t.created_at, t.updated_at,
                           t.session_id, t.model_id, t.mode, m.name AS model_name, t.result,
                           COUNT(e.event_id) AS event_count
                    FROM tasks t
                    LEFT JOIN events e ON t.task_id = e.task_id
                    LEFT JOIN models m ON m.model_id = t.model_id
                    WHERE t.session_id = ?
                    GROUP BY t.task_id, t.query, t.status, t.provider, t.created_at, t.updated_at,
                             t.session_id, t.model_id, t.mode, m.name, t.result
                    ORDER BY t.created_at DESC
                    """,
                    (session_id,),
                ).fetchall()
            else:
                rows = self._conn.execute(
                    """
                    SELECT t.task_id, t.query, t.status, t.provider, t.created_at, t.updated_at,
                           t.session_id, t.model_id, t.mode, m.name AS model_name, t.result,
                           COUNT(e.event_id) AS event_count
                    FROM tasks t
                    LEFT JOIN events e ON t.task_id = e.task_id
                    LEFT JOIN models m ON m.model_id = t.model_id
                    GROUP BY t.task_id, t.query, t.status, t.provider, t.created_at, t.updated_at,
                             t.session_id, t.model_id, t.mode, m.name, t.result
                    ORDER BY t.created_at DESC
                    """
                ).fetchall()
            return [
                {
                    "task_id": row["task_id"],
                    "query": row["query"],
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
            return [_SqliteTaskStore._event_to_dict(row) for row in rows]

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
                return [_SqliteTaskStore._event_to_dict(row) for row in rows]

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
            return [_SqliteTaskStore._event_to_dict(row) for row in rows]

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
                [_SqliteTaskStore._event_to_dict(row) for row in rows],
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

    def finish_task(
        self,
        task_id: str,
        success: bool,
        result: str | None = None,
        status: TaskStatus | None = None,
    ) -> None:
        final_status = status if status is not None else (TaskStatus.SUCCESS if success else TaskStatus.FAILED)
        with self._lock:
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


monitor_store = _SqliteTaskStore()
