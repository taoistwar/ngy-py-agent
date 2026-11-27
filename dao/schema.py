"""Schema creation and the migrations an older database needs on startup."""

from __future__ import annotations

import json
from datetime import UTC, datetime


class _SchemaMixin:
    """Tables, index creation and the column backfills for existing databases."""

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
                    icon TEXT NOT NULL DEFAULT '',
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
                    name TEXT NOT NULL DEFAULT '',
                    provider TEXT NOT NULL,
                    status TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    session_id TEXT,
                    model_id TEXT,
                    mode TEXT NOT NULL DEFAULT 'build',
                    resume_count INTEGER NOT NULL DEFAULT 0
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
            # One plan per conversation, replaced whole by ``todo_write``. It lives
            # beside the session rather than beside the task because a follow-up task
            # continues the same checklist (see ``dao/todos.py``).
            self._conn.execute(
                """
                CREATE TABLE IF NOT EXISTS session_todos (
                    session_id TEXT PRIMARY KEY,
                    items TEXT NOT NULL,
                    task_id TEXT NOT NULL DEFAULT '',
                    updated_at TEXT NOT NULL
                )
                """
            )
            # The workspace's task board: work items with prerequisites and an owner.
            # Board tasks are not ``tasks`` (agent runs) - see ``dao/board_tasks.py``.
            self._conn.execute(
                """
                CREATE TABLE IF NOT EXISTS board_tasks (
                    board_id TEXT NOT NULL,
                    task_id TEXT NOT NULL,
                    subject TEXT NOT NULL,
                    description TEXT NOT NULL DEFAULT '',
                    status TEXT NOT NULL,
                    owner TEXT,
                    blocked_by TEXT NOT NULL DEFAULT '[]',
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    PRIMARY KEY (board_id, task_id)
                )
                """
            )
            self._ensure_task_columns()
            self._ensure_session_columns()
            self._ensure_agent_columns()
            # Scheduled tasks: the definition ("0 9 * * *" + prompt) and one row per
            # attempt, pointing at the session and task that attempt created. The
            # task keeps its own status, so a run row never has to be kept in sync.
            self._conn.execute(
                """
                CREATE TABLE IF NOT EXISTS schedules (
                    schedule_id TEXT PRIMARY KEY,
                    name TEXT NOT NULL DEFAULT '',
                    cron TEXT NOT NULL,
                    prompt TEXT NOT NULL,
                    agent_id TEXT NOT NULL DEFAULT 'build',
                    model_id TEXT,
                    workspace_id TEXT,
                    -- Empty follows the global confirmation mode. A value pins this
                    -- schedule's runs: nobody is present to answer a prompt.
                    permission_mode TEXT NOT NULL DEFAULT '',
                    enabled INTEGER NOT NULL DEFAULT 1,
                    recurring INTEGER NOT NULL DEFAULT 1,
                    last_fired TEXT,
                    last_run_at TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )
                """
            )
            self._conn.execute(
                """
                CREATE TABLE IF NOT EXISTS schedule_runs (
                    run_id TEXT PRIMARY KEY,
                    schedule_id TEXT NOT NULL,
                    trigger TEXT NOT NULL,
                    session_id TEXT NOT NULL DEFAULT '',
                    task_id TEXT NOT NULL DEFAULT '',
                    status TEXT NOT NULL,
                    error TEXT NOT NULL DEFAULT '',
                    created_at TEXT NOT NULL
                )
                """
            )
            self._ensure_schedule_columns()
            self._conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_events_task_id_id ON events(task_id, id)"
            )
            self._conn.execute("CREATE INDEX IF NOT EXISTS idx_tasks_created_at ON tasks(created_at)")
            self._conn.execute("CREATE INDEX IF NOT EXISTS idx_tasks_session_id ON tasks(session_id)")
            self._conn.execute("CREATE INDEX IF NOT EXISTS idx_sessions_workspace_id ON sessions(workspace_id)")
            self._conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_schedule_runs_schedule "
                "ON schedule_runs(schedule_id, created_at)"
            )
            self._conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_schedule_runs_task ON schedule_runs(task_id)"
            )
            self._conn.commit()

        # Outside the block above: the LLM store takes the same lock itself, and the
        # migration it may run is not something to hold a second lock across.
        self.llm.ensure_schema()

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
        if "name" not in existing:
            self._conn.execute("ALTER TABLE tasks ADD COLUMN name TEXT NOT NULL DEFAULT ''")
        if "resume_count" not in existing:
            # How many times a restarted process has picked this task up. It is what
            # stops a task that kills the process on every attempt from being resumed
            # forever (see ``task_recovery``).
            self._conn.execute(
                "ALTER TABLE tasks ADD COLUMN resume_count INTEGER NOT NULL DEFAULT 0"
            )

    def _ensure_session_columns(self) -> None:
        rows = self._conn.execute("PRAGMA table_info(sessions)").fetchall()
        existing = {row["name"] for row in rows}
        if "workspace_id" not in existing:
            self._conn.execute("ALTER TABLE sessions ADD COLUMN workspace_id TEXT")

    def _ensure_agent_columns(self) -> None:
        rows = self._conn.execute("PRAGMA table_info(agents)").fetchall()
        existing = {row["name"] for row in rows}
        if "icon" not in existing:
            self._conn.execute("ALTER TABLE agents ADD COLUMN icon TEXT NOT NULL DEFAULT ''")

    def _ensure_schedule_columns(self) -> None:
        rows = self._conn.execute("PRAGMA table_info(schedules)").fetchall()
        existing = {row["name"] for row in rows}
        if "permission_mode" not in existing:
            # Added after schedules shipped: an unattended run inheriting "ask" parks
            # on a confirmation until it times out, so it has to be pinnable per row.
            self._conn.execute(
                "ALTER TABLE schedules ADD COLUMN permission_mode TEXT NOT NULL DEFAULT ''"
            )

    def _seed_default_agents(self) -> None:
        """Insert the built-in build/ask/plan agents derived from the mode configs.

        Rows that predate a config field (today: ``icon``) are backfilled when the
        stored value is still empty, so an existing database picks the defaults up.
        """
        from agent.modes import MODE_CONFIGS

        now = datetime.now(UTC).isoformat()
        with self._lock:
            for name, config in MODE_CONFIGS.items():
                row = self._conn.execute(
                    "SELECT icon FROM agents WHERE agent_id = ?",
                    (name,),
                ).fetchone()
                if row is not None:
                    default_icon = config.get("icon", "")
                    if default_icon and not (row["icon"] or ""):
                        self._conn.execute(
                            "UPDATE agents SET icon = ? WHERE agent_id = ?",
                            (default_icon, name),
                        )
                    continue
                tool_names = config.get("tool_names")
                self._conn.execute(
                    """
                    INSERT INTO agents (
                        agent_id, name, icon, description, system_prompt,
                        tool_names, skill_names, mcp_servers, is_builtin,
                        created_at, updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        name,
                        config.get("label", name),
                        config.get("icon", ""),
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
